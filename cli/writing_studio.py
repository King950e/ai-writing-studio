import sys
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3.6:latest"

PROMPTS = {
    "blog":    "You are a friendly blog writer. Write a clear, engaging blog post with a hook, a few subheadings, and a short wrap-up. Natural, human tone.",
    "email":   "You are a clear professional communicator. Turn the following into a concise, friendly email. Include a subject line at the top.",
    "caption": "You are a social media writer. Write 3 short, punchy captions based on the following. Casual and scroll-stopping. Number them 1 to 3.",
    "rewrite": "You are a sharp editor. Rewrite the following to be clearer, tighter, and more engaging, keeping the meaning and any real facts intact.",
}

def read_input(arg):
    try:
        with open(arg, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return arg

def call_ollama(prompt):
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False, "think": False},
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()["response"]
    except requests.exceptions.ConnectionError:
        print("Couldn't reach Ollama. Is it running? Check port 11434.")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("Ollama took too long to respond. Try again or use a smaller model.")
        sys.exit(1)

def main():
    if len(sys.argv) < 3:
        print("Usage: python writing_studio.py <mode> <text_or_file> [tone]")
        print("Modes:", ", ".join(PROMPTS.keys()))
        sys.exit(1)

    mode = sys.argv[1].lower()
    if mode not in PROMPTS:
        print(f"Unknown mode '{mode}'. Choose from: {', '.join(PROMPTS.keys())}")
        sys.exit(1)

    user_input = read_input(sys.argv[2])
    tone = sys.argv[3] if len(sys.argv) > 3 else None
    instruction = PROMPTS[mode]
    prompt = f"{instruction}\n\nDo not invent fake facts, statistics, or quotes. Output only the result."
    if tone:
        prompt += f"\nWrite it in a {tone} tone."
    prompt += f"\n\nINPUT:\n{user_input}"

    result = call_ollama(prompt)
    print(result)
    with open(f"{mode}_output.md", "w", encoding="utf-8") as f:
        f.write(result)
    print(f"\nSaved {mode}_output.md")

if __name__ == "__main__":
    main()