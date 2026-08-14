import os
import httpx

DEFAULT_MODEL = "llama3.1"
DEFAULT_HOST = "http://localhost:11434"


def send_prompt(prompt_text, context):
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    model = os.environ.get("SPECOPS_OLLAMA_MODEL", DEFAULT_MODEL)

    response = httpx.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    response_text = response.json()["message"]["content"]

    meta = context.get("meta", {})
    return {
        "response_text": response_text,
        "prompt_hash": meta.get("prompt_hash"),
        "rag_sources": meta.get("rag_sources", []),
        "model": model,
    }
