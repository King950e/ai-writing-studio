import os
import sys
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3.6:latest"

FORMATS = {
    "tweet_thread.txt":      "Turn the following content into a Twitter/X thread of 4 to 6 short, punchy tweets. Number each tweet. Keep each one tight.",
    "linkedin_post.txt":     "Turn the following content into one professional but personable LinkedIn post. Open with a strong first line, keep it skimmable, end with a light call to engage.",
    "newsletter_blurb.txt":  "Turn the following content into a short email newsletter blurb. Start with a subject line, then 2 short paragraphs, then a one-line sign-off.",
    "instagram_caption.txt": "Turn the following content into a short, punchy Instagram caption with a friendly hook and 3 to 5 relevant hashtags at the end.",
}

def read_input(arg):
    try:
        with open(arg, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return arg  # if it's not a file, treat it as raw text

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
    if len(sys.argv) < 2:
        print("Usage: python repurpose.py <content_text_or_file>")
        sys.exit(1)

    content = read_input(sys.argv[1])
    folder = "repurposed"
    os.makedirs(folder, exist_ok=True)

    for filename, instruction in FORMATS.items():
        print(f"Generating {filename} ...")
        prompt = f"{instruction}\n\nDo not invent fake facts or quotes. Output only the result.\n\nCONTENT:\n{content}"
        result = call_ollama(prompt)
        with open(os.path.join(folder, filename), "w", encoding="utf-8") as f:
            f.write(result)

    print(f"\nDone. All formats saved in the '{folder}' folder.")

if __name__ == "__main__":
    main()
