import os

_ADAPTERS = {
    "mock": "adapters.adapter_mock",
    "huggingface": "adapters.adapter_huggingface",
    "hf": "adapters.adapter_huggingface",
}


def get_send_prompt():
    """Return the send_prompt() callable selected via SPECOPS_MODEL (default: mock)."""
    name = os.environ.get("SPECOPS_MODEL", "mock").lower()
    module_path = _ADAPTERS.get(name)
    if module_path is None:
        raise SystemExit(
            f"Unknown SPECOPS_MODEL '{name}'. Available: {', '.join(sorted(set(_ADAPTERS)))}"
        )
    import importlib

    module = importlib.import_module(module_path)
    return module.send_prompt
