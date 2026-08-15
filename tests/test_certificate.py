import json
import os
import subprocess

import pytest

from core import certificate


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A throwaway git repo with one commit, so certificate.generate()'s
    git calls (branch, commit sha, author, diffstat) have something real
    to read instead of needing to be mocked line by line."""
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], check=True)
    (tmp_path / "greet.py").write_text("def greet(name):\n    return name\n")
    subprocess.run(["git", "add", "greet.py"], check=True)
    subprocess.run(["git", "commit", "-q", "-m", "specops: apply patch"], check=True)
    yield tmp_path


def _write_log_entry(**fields):
    os.makedirs("logs", exist_ok=True)
    entry = {
        "id": "x",
        "phase": "SPEC",
        "feature": "greet-function",
        "prompt_hash": "abc123def456",
        "rag_sources": [],
        "response_summary": "",
        "model": "mock",
        "validators_run": [],
        "status": None,
        "timestamp": "2026-01-01T00:00:00Z",
    }
    entry.update(fields)
    with open("logs/specops.log", "a") as f:
        f.write(json.dumps(entry) + "\n")


def test_generate_writes_a_certificate_with_the_pipeline_phases(git_repo):
    _write_log_entry(phase="SPEC", model="mock", rag_sources=["rags/ddd/x.md"])
    _write_log_entry(phase="PLAN", model="mock")
    _write_log_entry(
        phase="WORK", model="huggingface", validators_run=[], rag_sources=["rags/patterns/y.md"]
    )
    _write_log_entry(phase="REVIEW", model="n/a", validators_run=["tools/validators.sh"])

    path = certificate.generate("greet-function")

    assert os.path.exists(path)
    assert path.startswith("certificates/CHG-0001-greet-function")
    content = open(path).read()
    assert "greet-function" in content
    assert "**SPEC**: model `mock`" in content
    assert "**WORK**: model `huggingface`" in content
    assert "rags/ddd/x.md" in content
    assert "rags/patterns/y.md" in content
    assert "tools/validators.sh" in content


def test_generate_only_credits_features_that_match(git_repo):
    _write_log_entry(phase="SPEC", feature="other-feature")

    path = certificate.generate("greet-function")
    content = open(path).read()

    assert "**SPEC**: not recorded" in content


def test_generate_numbers_certificates_sequentially(git_repo):
    _write_log_entry(phase="SPEC")
    first = certificate.generate("greet-function")
    second = certificate.generate("greet-function")

    assert "CHG-0001" in first
    assert "CHG-0002" in second


def test_generate_with_no_log_entries_still_produces_a_certificate(git_repo):
    path = certificate.generate("undocumented-feature")
    content = open(path).read()

    assert "**SPEC**: not recorded" in content
    assert "(none retrieved)" in content
    assert "(no validators recorded)" in content
