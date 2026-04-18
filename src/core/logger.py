import json, os, time, uuid, re
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def _mask_secrets(s: str) -> str:
    # basic masking for tokens (heuristic)
    s = re.sub(r"(?:api_key|secret|token)[:=]\s*[\w-]{8,}", "<MASKED>", s, flags=re.I)
    return s

def audit_log(phase, prompt_meta, response):
    entry = {
        "id": str(uuid.uuid4()),
        "phase": phase,
        "prompt_hash": prompt_meta["prompt_hash"],
        "rag_sources": prompt_meta.get("rag_sources", []),
        "response_summary": _mask_secrets(response.get("response_text", "")[:400]),
        "model": response.get("model", "mock"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    path = f"{LOG_DIR}/specops.log"
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")

