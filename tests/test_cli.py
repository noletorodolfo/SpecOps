import os
import types
from argparse import Namespace

import pytest

from cli import specops_cli
from core.state_machine import StateMachine, APPLY_PENDING, WORK_DRAFT, REVIEW_PATCH


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    """Every test runs in its own throwaway directory so state/out/logs
    never touch the real project files."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def _write_patch(feature):
    os.makedirs("out", exist_ok=True)
    with open(f"out/{feature}.patch", "w") as f:
        f.write("diff --git a/x b/x\n")


def test_clean_diff_output_leaves_no_newline_marker_unprefixed():
    raw = (
        "--- /dev/null\n"
        "+++ b/x.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+print('hi')\n"
        "\\ No newline at end of file\n"
    )
    out = specops_cli.clean_diff_output(raw)
    assert "+\\ No newline" not in out
    assert "\\ No newline at end of file" in out


def test_clean_diff_output_preserves_indented_code_in_new_file_hunk():
    raw = "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\n+def f():\n    return 1\n"
    assert specops_cli.clean_diff_output(raw) == (
        "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\n+def f():\n+    return 1\n"
    )


def test_clean_diff_output_repairs_each_file_in_a_multi_file_diff():
    raw = (
        "diff --git a/impl.py b/impl.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/impl.py\n"
        "@@ -0,0 +1,999 @@\n"
        "def greet(name):\n"
        "    return name\n"
        "diff --git a/test_impl.py b/test_impl.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/test_impl.py\n"
        "@@ -0,0 +1,999 @@\n"
        "+import impl\n"
        "assert impl.greet('x')\n"
    )
    assert specops_cli.clean_diff_output(raw) == (
        "diff --git a/impl.py b/impl.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/impl.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def greet(name):\n"
        "+    return name\n"
        "diff --git a/test_impl.py b/test_impl.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/test_impl.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+import impl\n"
        "+assert impl.greet('x')\n"
    )


def test_clean_diff_output_strips_markdown_fence():
    wrapped = "```diff\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,1 @@\n+print('hi')\n```"
    assert specops_cli.clean_diff_output(wrapped) == (
        "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,1 @@\n+print('hi')\n"
    )


def test_clean_diff_output_repairs_missing_plus_prefix():
    raw = "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\nline one\nline two\n"
    assert specops_cli.clean_diff_output(raw) == (
        "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\n+line one\n+line two\n"
    )


def test_clean_diff_output_leaves_well_formed_diff_untouched():
    good = "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,1 @@\n+print('hi')\n"
    assert specops_cli.clean_diff_output(good) == good


def test_clean_diff_output_repairs_doubled_plus_marker():
    raw = "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\n+line one\n++line two\n"
    assert specops_cli.clean_diff_output(raw) == (
        "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\n+line one\n+line two\n"
    )


def test_clean_diff_output_repairs_wrong_hunk_count():
    raw = "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,999 @@\n+line one\n+line two\n"
    assert specops_cli.clean_diff_output(raw) == (
        "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\n+line one\n+line two\n"
    )


def test_validate_feature_accepts_valid_names():
    assert specops_cli.validate_feature("nova-feature_1") == "nova-feature_1"


@pytest.mark.parametrize("bad", ["../etc", "feat ure", "feat;rm -rf", "feat/ure", ""])
def test_validate_feature_rejects_invalid_names(bad):
    with pytest.raises(SystemExit):
        specops_cli.validate_feature(bad)


def test_apply_blocked_when_not_apply_pending(monkeypatch):
    feature = "blocked-feature"
    _write_patch(feature)
    StateMachine().advance(feature, REVIEW_PATCH)

    called = {"git": False}

    def fake_run(cmd, *a, **k):
        called["git"] = True
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(specops_cli.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        specops_cli.cmd_apply(Namespace(feature=feature))

    assert called["git"] is False, "apply must not touch git before review passes"
    assert StateMachine().load(feature)["stage"] == REVIEW_PATCH


def test_apply_proceeds_when_apply_pending(monkeypatch):
    feature = "ready-feature"
    _write_patch(feature)
    StateMachine().advance(feature, APPLY_PENDING)

    monkeypatch.setattr("builtins.input", lambda _: "yes")

    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return types.SimpleNamespace(returncode=0, stdout="main\n")
        return types.SimpleNamespace(returncode=1)  # branch doesn't exist yet

    monkeypatch.setattr(specops_cli.subprocess, "run", fake_run)

    specops_cli.cmd_apply(Namespace(feature=feature))

    assert any(c[:2] == ["git", "checkout"] for c in calls)
    assert any(c == ["git", "checkout", "-b", f"feat/{feature}"] for c in calls)
    assert any(c[:2] == ["git", "apply"] for c in calls)
    assert any(c[:2] == ["git", "commit"] for c in calls)
    assert StateMachine().load(feature)["stage"] == "APPLIED"


def test_apply_replaces_stale_branch_from_a_previous_apply(monkeypatch):
    feature = "redo-feature"
    _write_patch(feature)
    StateMachine().advance(feature, APPLY_PENDING)

    monkeypatch.setattr("builtins.input", lambda _: "yes")

    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return types.SimpleNamespace(returncode=0, stdout="main\n")
        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            return types.SimpleNamespace(returncode=0)  # branch already exists
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(specops_cli.subprocess, "run", fake_run)

    specops_cli.cmd_apply(Namespace(feature=feature))

    branch = f"feat/{feature}"
    assert any(c == ["git", "branch", "-D", branch] for c in calls), (
        "an existing branch from a prior apply must be replaced, not reused"
    )
    assert any(c == ["git", "checkout", "-b", branch] for c in calls)
    # Never a plain checkout of the existing branch — that's exactly what
    # fails when freshly regenerated, untracked files collide with it.
    assert not any(c == ["git", "checkout", branch] for c in calls)


def test_apply_aborted_when_user_declines(monkeypatch):
    feature = "declined-feature"
    _write_patch(feature)
    StateMachine().advance(feature, APPLY_PENDING)

    monkeypatch.setattr("builtins.input", lambda _: "no")

    called = {"git": False}

    def fake_run(cmd, *a, **k):
        called["git"] = True
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(specops_cli.subprocess, "run", fake_run)

    specops_cli.cmd_apply(Namespace(feature=feature))

    assert called["git"] is False
    assert StateMachine().load(feature)["stage"] == APPLY_PENDING


def test_review_pass_sets_apply_pending(monkeypatch):
    feature = "review-pass"
    StateMachine().advance(feature, REVIEW_PATCH)

    monkeypatch.setattr(
        specops_cli.subprocess,
        "run",
        lambda cmd, *a, **k: types.SimpleNamespace(returncode=0),
    )

    specops_cli.cmd_review(Namespace(feature=feature))

    assert StateMachine().load(feature)["stage"] == APPLY_PENDING


def test_review_fail_resets_to_work_draft(monkeypatch):
    feature = "review-fail"
    StateMachine().advance(feature, REVIEW_PATCH)

    monkeypatch.setattr(
        specops_cli.subprocess,
        "run",
        lambda cmd, *a, **k: types.SimpleNamespace(returncode=1),
    )

    with pytest.raises(SystemExit):
        specops_cli.cmd_review(Namespace(feature=feature))

    assert StateMachine().load(feature)["stage"] == WORK_DRAFT
