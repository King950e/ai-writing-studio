import json
import os
import sys

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.getenv("MODEL", "qwen3.6:latest")
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))
OUTPUT_FILE = "tailored_resume.md"

# Text from the blank template. If any of it is still in the file, the AI has nothing real to work with.
PLACEHOLDERS = ["Your Name", "you@email.com", "Your Job Title", "Company Name", "A real thing you did"]


def load_work_history(path="work_history.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Could not find {path}. Make sure it's in this folder.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"{path} has a JSON mistake on line {e.lineno}, column {e.colno}: {e.msg}")
        print("Check for a missing comma or quote near that spot.")
        sys.exit(1)

    leftovers = [p for p in PLACEHOLDERS if p in json.dumps(data)]
    if leftovers:
        print(f"{path} still has template text in it: {', '.join(leftovers)}")
        print("Replace it with your real info first, or the resume will be filled with placeholders.")
        sys.exit(1)
    return data


def read_job_description(arg):
    try:
        with open(arg, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return arg  # not a file, so treat it as pasted text


def build_prompt(work_history, job_description):
    return f"""You are a resume writing assistant. Below is a candidate's full work history as JSON,
and a job description. Select and lightly rewrite ONLY the most relevant experience bullets,
projects, certifications, and skills to match the job.

Rules:
- Do NOT invent any experience, numbers, tools, or certifications that are not in the work history.
- Use the candidate's real name and contact info exactly as given. Never use placeholders like [Your Name].
- Use the job's own keywords where they truthfully match the candidate's experience.
- Keep it to about one page.

Output a clean resume in this order, using these exact headers:
Name and contact line, then Summary, Experience, Projects, Certifications, Education, Skills.
Output only the resume.

WORK HISTORY:
{json.dumps(work_history, indent=2)}

JOB DESCRIPTION:
{job_description}
"""


def call_ollama(prompt):
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "think": False,  # skip the long "thinking" step
                # Room for the work history + job description + answer.
                # Ollama's small default can cut the answer off and leave it blank.
                "options": {"num_ctx": NUM_CTX},
            },
            timeout=600,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        print("Couldn't reach Ollama. Is it running? Check port 11434.")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("Ollama took too long to respond. Try again, or shorten the job description.")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"Ollama returned an error: {e}. Is the model '{MODEL}' pulled? Try: ollama pull {MODEL}")
        sys.exit(1)

    if not text:
        print("The model sent back an empty answer, so nothing was saved.")
        print("Try again, or raise NUM_CTX (for example: set NUM_CTX=16384).")
        sys.exit(1)
    return text


def main():
    if len(sys.argv) < 2:
        print("Usage: python tailor_resume.py <job_description_file_or_text>")
        sys.exit(1)

    work_history = load_work_history()
    job_description = read_job_description(sys.argv[1])

    print("Tailoring your resume... this can take a minute or two.")
    result = call_ollama(build_prompt(work_history, job_description))
    print(result)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"\nSaved to {OUTPUT_FILE}")
    print("Read it over before sending. Make sure every line is true.")


if __name__ == "__main__":
    main()
