import requests

#chatbot to keep on talking
while True:
    prompt = input("Prompt (or 'quit'): ")
    if prompt.lower() == "quit":
        break
#what port number it will be on
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "qwen3.6:latest",
            "prompt": prompt,
            "stream": False,
            "think": False
        },
        timeout=300
    )
# response
    print(response.json()["response"])
    print()