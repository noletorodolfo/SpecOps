"""Semantic index over a project's own source code.

Same machinery as the notes index (embed + FAISS + top-k), pointed at the
project's tracked files instead of `.specops/rags/*.md`. This is what
lets the work phase discover which existing files are relevant to a
request, rather than depending on the plan happening to name them.

Kept in a separate index from the notes: notes are curated guidance that
governance scopes by phase, code is raw project material. Mixing them
would let a stray source file outrank the guidance a phase is supposed
to follow.
"""

import os
import pickle
import subprocess

from rags import embedding

INDEX_PATH = ".specops/index/code.faiss"
META_PATH = ".specops/index/code_meta.pkl"

# Chunks are line windows: big enough to hold a whole function, small
# enough that retrieval points somewhere specific. Overlap keeps a
# definition from being split across a boundary and matching neither half.
CHUNK_LINES = 60
CHUNK_OVERLAP = 10

INDEXABLE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs",
    ".sql", ".sh", ".bash", ".lua", ".vim",
    ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".md", ".rst", ".txt",
    ".html", ".css", ".scss",
    ".prisma", ".graphql", ".proto",
}

# Machine-generated or vendored: real files, but nothing a human wrote as
# an example of how this project does things.
SKIP_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "go.sum", "composer.lock",
}
SKIP_DIR_PARTS = {
    ".git", ".specops", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", ".next", ".cache", "vendor", "target",
    "coverage", ".pytest_cache", ".mypy_cache",
}

MAX_FILE_BYTES = 200_000


def _tracked_files(root):
    """Prefer `git ls-files`: it already honours .gitignore and skips
    untracked junk, which is exactly the filter we want and reimplementing
    it by hand would only approximate."""
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True
    )
    if result.returncode == 0:
        return [line for line in result.stdout.splitlines() if line.strip()]

    # Not a git repo — fall back to a plain walk with the same exclusions.
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            found.append(os.path.relpath(full, root))
    return found


def indexable_files(root):
    """Project files worth embedding, as paths relative to `root`."""
    selected = []
    for path in _tracked_files(root):
        parts = set(path.split(os.sep))
        if parts & SKIP_DIR_PARTS:
            continue
        if os.path.basename(path) in SKIP_NAMES:
            continue
        if os.path.splitext(path)[1].lower() not in INDEXABLE_SUFFIXES:
            continue
        full = os.path.join(root, path)
        try:
            if not os.path.isfile(full) or os.path.getsize(full) > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        selected.append(path)
    return sorted(selected)


def chunk_file(path, content):
    """Split into overlapping line windows, each tagged with its real line
    range so a retrieval result can point at a specific place in a file."""
    lines = content.splitlines()
    if not lines:
        return []

    chunks = []
    step = max(1, CHUNK_LINES - CHUNK_OVERLAP)
    for start in range(0, len(lines), step):
        window = lines[start : start + CHUNK_LINES]
        if not window or not any(line.strip() for line in window):
            continue
        chunks.append(
            {
                "path": path,
                "start_line": start + 1,
                "end_line": start + len(window),
                "text": "\n".join(window),
            }
        )
        if start + CHUNK_LINES >= len(lines):
            break
    return chunks


def build_index(root="."):
    """(Re)build the code index. Returns (files_indexed, chunks_indexed)."""
    import faiss

    metas = []
    texts = []
    for path in indexable_files(root):
        try:
            with open(os.path.join(root, path), encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable despite the suffix
        for chunk in chunk_file(path, content):
            texts.append(chunk["text"])
            metas.append(chunk)

    index_path = os.path.join(root, INDEX_PATH)
    meta_path = os.path.join(root, META_PATH)
    os.makedirs(os.path.dirname(index_path), exist_ok=True)

    if not texts:
        for stale in (index_path, meta_path):
            if os.path.exists(stale):
                os.remove(stale)
        return 0, 0

    embeddings = embedding.encode(texts)
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    faiss.write_index(index, index_path)
    with open(meta_path, "wb") as f:
        pickle.dump(metas, f)

    return len({m["path"] for m in metas}), len(metas)


def retrieve_code(query, k=6, root="."):
    """Top-k code chunks for a query, best first. Empty if never indexed."""
    import faiss

    index_path = os.path.join(root, INDEX_PATH)
    meta_path = os.path.join(root, META_PATH)
    if not (os.path.exists(index_path) and os.path.exists(meta_path)):
        return []

    with open(meta_path, "rb") as f:
        metas = pickle.load(f)
    if not metas:
        return []

    index = faiss.read_index(index_path)
    query_embedding = embedding.encode([query])
    _, ids = index.search(query_embedding, min(k, len(metas)))

    results = []
    for idx in ids[0]:
        if 0 <= idx < len(metas):
            results.append(metas[idx])
    return results


def is_indexed(root="."):
    return os.path.exists(os.path.join(root, INDEX_PATH))
