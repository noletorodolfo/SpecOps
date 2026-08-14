import os
import httpx

DEFAULT_MODEL = "gpt-4o-mini"
API_URL = "https://api.openai.com/v1/chat/completions"


def send_prompt(prompt_text, context):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. Add it to .env (never commit it) or export it in your shell."
        )
    model = os.environ.get("SPECOPS_OPENAI_MODEL", DEFAULT_MODEL)

    response = httpx.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "max_tokens": 1024,
        },
        timeout=60,
    )
    response.raise_for_status()
    response_text = response.json()["choices"][0]["message"]["content"]

    meta = context.get("meta", {})
    return {
        "response_text": response_text,
        "prompt_hash": meta.get("prompt_hash"),
        "rag_sources": meta.get("rag_sources", []),
        "model": model,
    }
