import os
import subprocess

import pytest

from core import sandbox


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "committed.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _write_patch(root, body):
    path = root / "change.patch"
    path.write_text(body)
    return str(path)


NEW_FILE_PATCH = (
    "diff --git a/added.py b/added.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/added.py\n"
    "@@ -0,0 +1,1 @@\n"
    "+y = 2\n"
)


def test_worktree_contains_head_plus_the_patch(repo):
    patch = _write_patch(repo, NEW_FILE_PATCH)

    with sandbox.patched_worktree(str(repo), patch, ["added.py"]) as tree:
        assert os.path.exists(os.path.join(tree, "committed.py")), "HEAD content missing"
        assert open(os.path.join(tree, "added.py")).read() == "y = 2\n"


def test_the_real_working_tree_is_never_touched(repo):
    patch = _write_patch(repo, NEW_FILE_PATCH)

    with sandbox.patched_worktree(str(repo), patch, ["added.py"]):
        pass

    assert not (repo / "added.py").exists(), (
        "review must not leave the patch applied in the user's tree"
    )


def test_worktree_is_removed_afterwards(repo):
    patch = _write_patch(repo, NEW_FILE_PATCH)

    with sandbox.patched_worktree(str(repo), patch, ["added.py"]) as tree:
        captured = tree
    assert not os.path.exists(captured)

    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "specops-review" not in listed, "a stale worktree was left registered"


def test_worktree_is_cleaned_up_even_when_the_body_raises(repo):
    patch = _write_patch(repo, NEW_FILE_PATCH)
    captured = {}

    with pytest.raises(RuntimeError):
        with sandbox.patched_worktree(str(repo), patch, ["added.py"]) as tree:
            captured["path"] = tree
            raise RuntimeError("validators blew up")

    assert not os.path.exists(captured["path"])
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "specops-review" not in listed


def test_uncommitted_changes_to_patched_files_are_carried_in(repo):
    """work builds the patch against the *working tree*. If a target has
    uncommitted edits, a clean HEAD checkout wouldn't match and the patch
    would fail to apply — so those versions get seeded in first."""
    (repo / "committed.py").write_text("x = 1\nuncommitted_line = True\n")

    patch = _write_patch(
        repo,
        "diff --git a/committed.py b/committed.py\n"
        "--- a/committed.py\n"
        "+++ b/committed.py\n"
        "@@ -1,2 +1,3 @@\n"
        " x = 1\n"
        " uncommitted_line = True\n"
        "+added_by_patch = True\n",
    )

    with sandbox.patched_worktree(str(repo), patch, ["committed.py"]) as tree:
        content = open(os.path.join(tree, "committed.py")).read()

    assert "uncommitted_line = True" in content
    assert "added_by_patch = True" in content


def test_dependency_dirs_are_symlinked_not_copied(repo):
    os.makedirs(repo / "node_modules" / "pkg")
    (repo / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1\n")
    patch = _write_patch(repo, NEW_FILE_PATCH)

    with sandbox.patched_worktree(str(repo), patch, ["added.py"]) as tree:
        linked = os.path.join(tree, "node_modules")
        assert os.path.islink(linked), "dependencies should be linked, not copied"
        assert os.path.exists(os.path.join(linked, "pkg", "index.js"))


def test_a_patch_that_cannot_apply_raises(repo):
    patch = _write_patch(
        repo,
        "diff --git a/committed.py b/committed.py\n"
        "--- a/committed.py\n"
        "+++ b/committed.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-totally different content\n"
        "+replacement\n",
    )

    with pytest.raises(sandbox.SandboxError, match="did not apply"):
        with sandbox.patched_worktree(str(repo), patch, ["committed.py"]):
            pass


def test_is_git_repo(repo, tmp_path):
    assert sandbox.is_git_repo(str(repo)) is True

    plain = tmp_path.parent / "not-a-repo"
    plain.mkdir(exist_ok=True)
    assert sandbox.is_git_repo(str(plain)) is False
