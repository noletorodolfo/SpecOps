# minimal retrieve wrapper for the MVP
import pickle, faiss, os
INDEX_PATH = "rags/index.faiss"
META_PATH = "rags/meta.pkl"
from sentence_transformers import SentenceTransformer
MODEL = SentenceTransformer("all-MiniLM-L6-v2")

def retrieve_topk(phase, query, k=4):
    if not os.path.exists(INDEX_PATH) or not os.path.exists(META_PATH):
        return [], []
    index = faiss.read_index(INDEX_PATH)
    metas = pickle.load(open(META_PATH, "rb"))
    q_emb = MODEL.encode([query])
    D, I = index.search(q_emb, k)
    chunks = []
    sources = []
    for idx in I[0]:
        if idx < 0 or idx >= len(metas): continue
        path = metas[idx]["path"]
        text = open(path, "r", encoding="utf-8").read()
        chunks.append({"text": text[:1000], "path": path})
        sources.append(path)
    return chunks, sources

