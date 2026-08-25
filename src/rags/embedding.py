"""Shared sentence-transformers model for both indexes (notes and code).

Loaded lazily: importing this module is free, and commands that never
embed anything (`project init`, `apply`, `--help`) no longer pay the
model's load time or print its startup noise.
"""

MODEL_NAME = "all-MiniLM-L6-v2"

_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode(texts):
    return get_model().encode(texts)
