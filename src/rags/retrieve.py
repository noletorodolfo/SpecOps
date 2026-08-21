# minimal retrieve wrapper for the MVP
import pickle, faiss, os
INDEX_PATH = ".specops/rags/index.faiss"
META_PATH = ".specops/rags/meta.pkl"
from sentence_transformers import SentenceTransformer
MODEL = SentenceTransformer("all-MiniLM-L6-v2")

# Maps governance.yml framework identifiers to their rags/<dir> notes.
# "patterns" is cross-cutting and always eligible regardless of framework.
FRAMEWORK_DIRS = {
    "TOGAF": "togaf",
    "DDD": "ddd",
    "KLEPPMANN": "kleppmann",
    "AWS_SA_PRO": "aws_well_architected",
    "CKA": "cka",
    "TERRAFORM": "terraform",
    "AWS_DEVOPS": "aws_devops",
    "GOOGLE_ML": "google_ml",
    "DATABRICKS": "databricks",
    "ADR": "adr",
}


def retrieve_topk(frameworks, query, k=4):
    """frameworks: list of governance.yml framework ids for the current
    phase (e.g. ["TOGAF", "DDD"]). Only notes under those frameworks'
    directories (plus the always-eligible 'patterns' dir) are considered,
    so a spec-phase query can't surface a terraform note just because it
    happens to score well on raw embedding similarity."""
    if not os.path.exists(INDEX_PATH) or not os.path.exists(META_PATH):
        return [], []
    index = faiss.read_index(INDEX_PATH)
    metas = pickle.load(open(META_PATH, "rb"))
    if not metas:
        return [], []

    allowed_dirs = {FRAMEWORK_DIRS[f] for f in frameworks if f in FRAMEWORK_DIRS}
    allowed_dirs.add("patterns")

    q_emb = MODEL.encode([query])
    search_k = min(len(metas), max(k * 4, k))
    D, I = index.search(q_emb, search_k)

    chunks = []
    sources = []
    for idx in I[0]:
        if idx < 0 or idx >= len(metas):
            continue
        path = metas[idx]["path"]
        top_dir = path.split("/")[2] if path.startswith(".specops/rags/") else path.split("/")[0]
        if top_dir not in allowed_dirs:
            continue
        text = open(path, "r", encoding="utf-8").read()
        chunks.append({"text": text[:1000], "path": path})
        sources.append(path)
        if len(chunks) >= k:
            break
    return chunks, sources
