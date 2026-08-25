import os
import subprocess

import pytest

from rags import code_index


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    return tmp_path


def _commit_all(root):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=root, check=True)


def test_indexable_files_respects_gitignore(project):
    (project / ".gitignore").write_text("secret.py\n")
    (project / "kept.py").write_text("x = 1\n")
    (project / "secret.py").write_text("password = 'hunter2'\n")
    _commit_all(project)

    files = code_index.indexable_files(str(project))

    assert "kept.py" in files
    assert "secret.py" not in files, "gitignored files must never be indexed"


def test_indexable_files_skips_vendored_and_generated(project):
    os.makedirs(project / "node_modules" / "pkg", exist_ok=True)
    (project / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1\n")
    (project / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (project / "real.js").write_text("export const x = 1\n")
    subprocess.run(["git", "add", "-Af"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=project, check=True)

    files = code_index.indexable_files(str(project))

    assert "real.js" in files
    assert "package-lock.json" not in files
    assert not any("node_modules" in f for f in files)


def test_indexable_files_skips_specops_own_data(project):
    os.makedirs(project / ".specops" / "specs", exist_ok=True)
    (project / ".specops" / "specs" / "a.md").write_text("a spec\n")
    (project / "code.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-Af"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=project, check=True)

    files = code_index.indexable_files(str(project))

    assert "code.py" in files
    assert not any(f.startswith(".specops") for f in files), (
        "indexing SpecOps' own artifacts would feed generated specs back as 'code'"
    )


def test_indexable_files_skips_unknown_extensions(project):
    (project / "image.png").write_bytes(b"\x89PNG\r\n")
    (project / "code.py").write_text("x = 1\n")
    _commit_all(project)

    files = code_index.indexable_files(str(project))

    assert files == ["code.py"]


def test_chunk_file_produces_overlapping_line_windows():
    content = "\n".join(f"line{i}" for i in range(150)) + "\n"
    chunks = code_index.chunk_file("big.py", content)

    assert len(chunks) > 1
    assert chunks[0]["start_line"] == 1
    assert chunks[0]["path"] == "big.py"
    # windows overlap, so the second starts before the first one ended
    assert chunks[1]["start_line"] <= chunks[0]["end_line"]
    # the last window reaches the end of the file
    assert chunks[-1]["end_line"] == 150


def test_chunk_file_handles_short_and_empty_files():
    assert code_index.chunk_file("empty.py", "") == []
    assert code_index.chunk_file("blank.py", "\n\n\n") == []

    chunks = code_index.chunk_file("small.py", "x = 1\ny = 2\n")
    assert len(chunks) == 1
    assert chunks[0]["end_line"] == 2


def test_build_and_retrieve_finds_the_semantically_relevant_file(project):
    (project / "auth.py").write_text(
        "def login(username, password):\n"
        "    '''Authenticate a user and start a session.'''\n"
        "    return check_credentials(username, password)\n"
    )
    (project / "geometry.py").write_text(
        "def circle_area(radius):\n"
        "    '''Compute the area of a circle.'''\n"
        "    return 3.14159 * radius ** 2\n"
    )
    _commit_all(project)

    files, chunks = code_index.build_index(str(project))
    assert files == 2
    assert chunks >= 2

    results = code_index.retrieve_code("user login authentication", k=1, root=str(project))
    assert results, "retrieval returned nothing"
    assert results[0]["path"] == "auth.py"


def test_retrieve_returns_empty_when_never_indexed(project):
    assert code_index.retrieve_code("anything", root=str(project)) == []
    assert code_index.is_indexed(str(project)) is False


def test_build_index_on_empty_project_is_a_no_op(project):
    files, chunks = code_index.build_index(str(project))
    assert (files, chunks) == (0, 0)
    assert code_index.is_indexed(str(project)) is False
