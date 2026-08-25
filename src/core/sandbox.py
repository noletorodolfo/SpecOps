"""Run validators against the patch *applied*, not the tree as it is.

`review` used to run the project's validators against the working tree
while the patch was still sitting unapplied in `.specops/out/`. So the
generated code was never actually executed: a patch whose only test was
`assert 1 == 2` passed review, because that file did not exist on disk
yet. Review confirmed the *existing* tests still passed — which for a
new project is trivially true — while the certificate reported that
validators had run.

This builds a throwaway git worktree holding exactly what `apply` would
commit (HEAD + the patch's files), runs the validators there, and
discards it. Nothing touches the real working tree.
"""

import contextlib
import os
import shutil
import subprocess
import tempfile

# Dependency directories are symlinked rather than copied: a project's
# tests usually can't run without them, and copying node_modules would
# dominate review's runtime.
LINKED_DEPENDENCY_DIRS = ("node_modules", ".venv", "venv", "vendor")


class SandboxError(Exception):
    """Raised when the post-apply state can't be reproduced."""


def _git(root, *args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise SandboxError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def is_git_repo(root):
    return _git(root, "rev-parse", "--git-dir", check=False).returncode == 0


@contextlib.contextmanager
def patched_worktree(project_root, patch_path, touched_paths=()):
    """Yield a directory containing HEAD plus `patch_path` applied.

    `touched_paths` are the files the patch modifies. Their *working
    tree* versions are copied in before applying, because that's what
    the patch was computed against — if any of them has uncommitted
    changes, a patch built from the working tree would not apply to a
    clean HEAD checkout.
    """
    parent = tempfile.mkdtemp(prefix="specops-review-")
    worktree = os.path.join(parent, "tree")
    added = False
    try:
        _git(project_root, "worktree", "add", "--detach", "--quiet", worktree, "HEAD")
        added = True

        for rel in touched_paths:
            source = os.path.join(project_root, rel)
            if not os.path.isfile(source):
                continue  # the patch creates it; nothing to seed
            target = os.path.join(worktree, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)

        for name in LINKED_DEPENDENCY_DIRS:
            source = os.path.join(project_root, name)
            target = os.path.join(worktree, name)
            if os.path.isdir(source) and not os.path.exists(target):
                os.symlink(source, target)

        applied = subprocess.run(
            ["git", "apply", os.path.abspath(patch_path)],
            cwd=worktree,
            capture_output=True,
            text=True,
        )
        if applied.returncode != 0:
            raise SandboxError(
                f"patch did not apply to a clean checkout: {applied.stderr.strip()}"
            )

        yield worktree
    finally:
        if added:
            subprocess.run(
                ["git", "worktree", "remove", "--force", worktree],
                cwd=project_root,
                capture_output=True,
            )
        shutil.rmtree(parent, ignore_errors=True)
