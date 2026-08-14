import yaml
import hashlib
from rags.retrieve import retrieve_topk

def build_prompt(phase, profile, context, feature_notes):
    governance = yaml.safe_load(open("governance.yml"))
    profile_cfg = governance["profiles"][profile][phase]
    rag_chunks, rag_sources = retrieve_topk(
        profile_cfg.get("frameworks", []), context.get("feature", ""), k=4
    )
    system = profile_cfg["system_instructions"]
    prompt_parts = [
        f"SYSTEM: {system}",
        "RAG_EXCERPTS:",
        *[f"- {c['text']}" for c in rag_chunks],
        "USER:",
        feature_notes or str(context)
    ]
    prompt_text = "\n\n".join(prompt_parts)
    prompt_hash = hashlib.sha256(prompt_text.encode()).hexdigest()
    return {
        "prompt_text": prompt_text,
        "prompt_hash": prompt_hash,
        "rag_sources": rag_sources,
        "phase": phase,
        "feature": context.get("feature", ""),
    }

