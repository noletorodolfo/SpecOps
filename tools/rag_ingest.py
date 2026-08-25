#!/usr/bin/env python3
# simple chunker + FAISS indexer for notes (requires sentence-transformers, faiss)
import os, glob, pickle, sys
import faiss

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rags import embedding

INDEX_PATH = ".specops/rags/index.faiss"
META_PATH = ".specops/rags/meta.pkl"

def ingest():
    texts = []
    metas = []
    for md in glob.glob(".specops/rags/**/*.md", recursive=True):
        with open(md, "r", encoding="utf-8") as f:
            txt = f.read()
        texts.append(txt)
        metas.append({"path": md})
    if not texts:
        print("No .specops/rags/*.md files found.")
        return
    embs = embedding.encode(texts)
    d = embs.shape[1]
    index = faiss.IndexFlatL2(d)
    index.add(embs)
    faiss.write_index(index, INDEX_PATH)
    with open(META_PATH, "wb") as f:
        pickle.dump(metas, f)
    print("RAG ingest complete. Indexed", len(texts))

if __name__ == "__main__":
    ingest()

