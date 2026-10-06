"""AI Writing Studio - web version.

A small Flask app that lets a user pick a writing mode, paste some text,
and get a result back from a local Ollama model.

Two areas:
  /       public writing tools (blog, email, captions, rewrite, repurpose)
  /jobs   private job tools (resume, cover letter) that use YOUR work history.
          Protected by Cloudflare Access, and the app checks the Access login
          token itself too, so nobody can reach it by going around Cloudflare.

The answer is streamed back word by word. That looks nicer, and it also
keeps Cloudflare from cutting the connection (Cloudflare gives up on a
request if the server sends nothing for 100 seconds).
"""
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque

import jwt
import requests
from flask import Flask, Response, abort, jsonify, render_template, request, stream_with_context

# ---------- Settings (override with environment variables) ----------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.getenv("MODEL", "qwen3.6:latest")
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "4000"))
# Job postings are long, so the resume/cover letter modes get a bigger limit.
JOB_MAX_CHARS = int(os.getenv("JOB_MAX_CHARS", "15000"))
# How much text the model can hold at once. Too small and long answers come back blank.
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))
# Your work history lives on the server only (deployed by Ansible, never in Git).
WORK_HISTORY_PATH = os.getenv("WORK_HISTORY_PATH", "work_history.json")
# Requests allowed per visitor IP. A repurpose run uses 4 (one per format).
RATE_PER_MINUTE = int(os.getenv("RATE_PER_MINUTE", "10"))
RATE_PER_DAY = int(os.getenv("RATE_PER_DAY", "60"))
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))

# Cloudflare Access settings (from the Zero Trust dashboard).
CF_TEAM_DOMAIN = os.getenv("CF_TEAM_DOMAIN", "")      # e.g. preston.cloudflareaccess.com
CF_ACCESS_AUD = os.getenv("CF_ACCESS_AUD", "")        # the Access application's "Application Audience (AUD) Tag"
CF_CERTS_URL = os.getenv("CF_CERTS_URL", f"https://{CF_TEAM_DOMAIN}/cdn-cgi/access/certs")
# true = the whole site needs a login. false = only /jobs needs a login.
REQUIRE_CF_ACCESS = os.getenv("REQUIRE_CF_ACCESS", "false").lower() == "true"
LOG_FILE = os.getenv("LOG_FILE", "studio.log")

# ---------- Writing modes ----------
RULES = "Do not invent fake facts, statistics, or quotes. Output only the result."

PROMPTS = {
    "blog": "You are a friendly blog writer. Write a clear, engaging blog post with a hook, a few subheadings, and a short wrap-up. Natural, human tone.",
    "email": "You are a clear professional communicator. Turn the following into a concise, friendly email. Include a subject line at the top.",
    "caption": "You are a social media writer. Write 3 short, punchy captions based on the following. Casual and scroll-stopping. Number them 1 to 3.",
    "rewrite": "You are a sharp editor. Rewrite the following to be clearer, tighter, and more engaging, keeping the meaning and any real facts intact.",
}

# "repurpose" runs every one of these, one request each.
REPURPOSE_FORMATS = {
    "Twitter/X thread": "Turn the following content into a Twitter/X thread of 4 to 6 short, punchy tweets. Number each tweet.",
    "LinkedIn post": "Turn the following content into one professional but personable LinkedIn post. Open with a strong first line, keep it skimmable, end with a light call to engage.",
    "Newsletter blurb": "Turn the following content into a short email newsletter blurb. Start with a subject line, then 2 short paragraphs, then a one-line sign-off.",
    "Instagram caption": "Turn the following content into a short, punchy Instagram caption with a friendly hook and 3 to 5 relevant hashtags at the end.",
}

# Job modes use the work history on the server plus a pasted job posting.
JOB_MODES = ["resume", "cover_letter"]

MODES = list(PROMPTS) + ["repurpose"] + JOB_MODES


def resume_prompt(work_history, job):
    return f"""You are a resume writing assistant. Below is a candidate's full work history as JSON,
and a job description. Select and lightly rewrite ONLY the most relevant experience bullets,
projects, certifications, and skills to match the job.

Rules:
- Do NOT invent any experience, numbers, tools, or certifications that are not in the work history.
- Do NOT exaggerate. Do not add words like "high-volume" or claim skills that are not listed.
- Use the candidate's real name and contact info exactly as given. Never use placeholders like [Your Name].
- Use the job's own keywords where they truthfully match the candidate's experience.
- Keep it to about one page.

Output a clean resume in this order, using these exact headers:
Name and contact line, then Summary, Experience, Projects, Certifications, Education, Skills.
Output only the resume.

WORK HISTORY:
{json.dumps(work_history, indent=2)}

JOB DESCRIPTION:
{job}
"""


def cover_letter_prompt(work_history, job, company):
    name = work_history.get("name", "")
    return f"""You are a cover letter writing assistant. Below is a candidate's full work history as JSON,
and a job description. Write a natural, concise THREE-paragraph cover letter for the company "{company}",
tailored to the job description. Reference specific relevant experience from the work history.

Rules:
- Do NOT invent or exaggerate any experience, numbers, tools, availability, or certifications.
- Use the dates in the work history exactly. Finished programs are finished, not in progress.
- Address it "Dear Hiring Manager,".
- Sign it "Sincerely," followed by {name}. Never use placeholders like [Your Name] or [Date].
- Output only the letter, with no preamble or explanation.

WORK HISTORY:
{json.dumps(work_history, indent=2)}

JOB DESCRIPTION:
{job}
"""


class SetupError(Exception):
    pass


def load_work_history():
    try:
        with open(WORK_HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise SetupError("Resume modes are not set up yet: work_history.json is missing on the server.")
    except json.JSONDecodeError as e:
        raise SetupError(f"work_history.json has a JSON mistake on line {e.lineno}.")
    # Catch a blank or template copy, so the AI isn't asked to build a resume out of nothing.
    placeholders = ["Your Name", "you@email.com", "Your Job Title", "Company Name", "A real thing you did"]
    text = json.dumps(data)
    if not str(data.get("name", "")).strip() or not data.get("experience") or any(p in text for p in placeholders):
        raise SetupError("work_history.json on the server is still the blank template. Fill in your real info and redeploy.")
    return data

# ---------- App setup ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger("studio")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # reject huge request bodies


def client_ip():
    """Real visitor IP. Cloudflare puts it in CF-Connecting-IP.
    Safe to trust because the firewall only lets the tunnel reach this app."""
    return request.headers.get("CF-Connecting-IP") or request.remote_addr or "unknown"


class RateLimiter:
    """Simple in-memory limiter: remembers request times per IP.
    Works because gunicorn runs a single worker process."""

    def __init__(self, per_minute, per_day):
        self.limits = [(60, per_minute), (86400, per_day)]
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 86400:
                q.popleft()
            for window, limit in self.limits:
                if sum(1 for t in q if now - t <= window) >= limit:
                    return False
            q.append(now)
            return True


limiter = RateLimiter(RATE_PER_MINUTE, RATE_PER_DAY)


_jwks_client = None


def access_user():
    """Return the logged-in email if the request carries a valid Cloudflare Access token, else None.
    Checks the token's signature against Cloudflare's public keys, so it can't be faked."""
    global _jwks_client
    token = request.headers.get("Cf-Access-Jwt-Assertion")
    if not token or not CF_TEAM_DOMAIN or not CF_ACCESS_AUD:
        return None
    try:
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(CF_CERTS_URL, cache_keys=True)
        key = _jwks_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256"],
            audience=CF_ACCESS_AUD, issuer=f"https://{CF_TEAM_DOMAIN}",
        )
        return claims.get("email", "unknown")
    except Exception as e:  # bad, expired, or forged token
        log.warning("access token rejected ip=%s error=%s", client_ip(), e)
        return None


def is_private_path(path):
    return path == "/jobs" or path.startswith("/jobs/") or path.startswith("/api/job")


@app.before_request
def require_cloudflare_access():
    if request.path == "/health":
        return
    if REQUIRE_CF_ACCESS or is_private_path(request.path):
        if not access_user():
            abort(403)


def build_prompt(instruction, text, tone):
    prompt = f"{instruction}\n\n{RULES}"
    if tone:
        prompt += f"\nWrite it in a {tone} tone."
    return prompt + f"\n\nINPUT:\n{text}"


def stream_ollama(prompt, mode, ip, chars):
    """Yield the model's answer piece by piece as it is generated."""
    start = time.time()
    try:
        with requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": True,
                "think": False,
                "options": {"num_ctx": NUM_CTX},
            },
            stream=True,
            timeout=OLLAMA_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("response"):
                    yield chunk["response"]
                if chunk.get("done"):
                    break
        log.info("mode=%s ip=%s chars=%d seconds=%.1f", mode, ip, chars, time.time() - start)
    except requests.exceptions.ConnectionError:
        log.error("mode=%s ip=%s error=ollama unreachable", mode, ip)
        yield "\n\n[Error: couldn't reach Ollama. Is it running?]"
    except requests.exceptions.Timeout:
        log.error("mode=%s ip=%s error=timeout", mode, ip)
        yield "\n\n[Error: the model took too long to respond. Try a shorter input.]"
    except (requests.exceptions.HTTPError, ValueError) as e:
        log.error("mode=%s ip=%s error=%s", mode, ip, e)
        yield f"\n\n[Error from Ollama: {e}]"


# ---------- Routes ----------
def render_page(page):
    return render_template(
        "index.html",
        page=page,
        formats=list(REPURPOSE_FORMATS),
        max_chars=MAX_INPUT_CHARS,
        job_max_chars=JOB_MAX_CHARS,
    )


@app.get("/")
def index():
    return render_page("writing")


@app.get("/jobs")
def jobs_page():
    return render_page("jobs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/generate")
@app.post("/api/job")
def generate():
    if not limiter.allow(client_ip()):
        abort(429)
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "")).lower()
    text = str(data.get("text", "")).strip()
    tone = str(data.get("tone", "")).strip()[:40]
    fmt = str(data.get("format", ""))
    company = str(data.get("company", "")).strip()[:100]

    job_api = request.path == "/api/job"
    allowed = JOB_MODES if job_api else [m for m in MODES if m not in JOB_MODES]
    if mode not in allowed:
        return jsonify(error=f"Unknown mode. Choose from: {', '.join(allowed)}"), 400
    if not text:
        return jsonify(error="Please enter some text."), 400
    limit = JOB_MAX_CHARS if mode in JOB_MODES else MAX_INPUT_CHARS
    if len(text) > limit:
        return jsonify(error=f"Input is too long ({len(text)} characters). The limit is {limit}."), 400

    if mode in JOB_MODES:
        if mode == "cover_letter" and not company:
            return jsonify(error="Please enter the company name."), 400
        try:
            history = load_work_history()
        except SetupError as e:
            return jsonify(error=str(e)), 503
        if mode == "resume":
            prompt = resume_prompt(history, text)
        else:
            prompt = cover_letter_prompt(history, text, company)
        body = stream_with_context(stream_ollama(prompt, mode, client_ip(), len(text)))
        return Response(body, mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if mode == "repurpose":
        if fmt not in REPURPOSE_FORMATS:
            return jsonify(error="Unknown repurpose format."), 400
        instruction = REPURPOSE_FORMATS[fmt]
        log_mode = f"repurpose/{fmt}"
    else:
        instruction = PROMPTS[mode]
        log_mode = mode

    prompt = build_prompt(instruction, text, tone)
    body = stream_with_context(stream_ollama(prompt, log_mode, client_ip(), len(text)))
    return Response(
        body,
        mimetype="text/event-stream",  # tells Cloudflare not to buffer the stream
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.errorhandler(429)
def too_many(e):
    return jsonify(error="Too many requests. Please wait a minute and try again."), 429


@app.errorhandler(403)
def forbidden(e):
    return jsonify(error="This area is private. Please log in."), 403


@app.errorhandler(413)
def too_large(e):
    return jsonify(error="Request is too large."), 413


if __name__ == "__main__":
    # Local testing only. On the server, gunicorn runs the app.
    app.run(host="127.0.0.1", port=5000, debug=True)
