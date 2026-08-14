import os
from huggingface_hub import InferenceClient

DEFAULT_MODEL = "meta-llama/Llama-3.1-8B-Instruct"


def send_prompt(prompt_text, context):
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "HF_TOKEN not set. Add it to .env (never commit it) or export it in your shell."
        )
    model = os.environ.get("SPECOPS_HF_MODEL", DEFAULT_MODEL)
    client = InferenceClient(model=model, token=token)

    completion = client.chat_completion(
        messages=[{"role": "user", "content": prompt_text}],
        max_tokens=1024,
    )
    response_text = completion.choices[0].message.content

    meta = context.get("meta", {})
    return {
        "response_text": response_text,
        "prompt_hash": meta.get("prompt_hash"),
        "rag_sources": meta.get("rag_sources", []),
        "model": model,
    }
