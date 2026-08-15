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


def test_extract_new_file_contents_reconstructs_multi_file_diff():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/a.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def f():\n"
        "+    return 1\n"
        "diff --git a/b.py b/b.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/b.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+x = 1\n"
    )
    files = specops_cli._extract_new_file_contents(diff)
    assert files == {"a.py": "def f():\n    return 1", "b.py": "x = 1"}


def test_check_python_syntax_flags_squashed_lines():
    # A model occasionally joins two logical lines with a literal ' +'
    # instead of a real newline; it's still a syntactically valid diff
    # line, but the resulting Python is broken.
    files = {
        "bad.py": "def f(self): +        return 1 +",
        "good.py": "def f():\n    return 1\n",
        "ignored.txt": "not python )(",
    }
    errors = specops_cli._check_python_syntax(files)
    assert len(errors) == 1
    assert errors[0].startswith("bad.py:")


def test_check_typescript_syntax_flags_broken_file():
    files = {
        "good.ts": "export function f(): number {\n    return 1;\n}\n",
        "bad.ts": "export function f(): number {\n    return 1;\n",  # missing '}'
        "ignored.py": "not typescript )(",
    }
    errors = specops_cli._check_typescript_syntax(files)
    assert len(errors) == 1
    assert errors[0].startswith("bad.ts:")


def test_check_typescript_syntax_ignores_unresolved_imports_and_test_globals():
    # Syntax-only: a spec file referencing an unresolved import and
    # jest-style globals (describe/it/expect) with no @types installed
    # must NOT be flagged — that's a type/semantic concern, not syntax.
    files = {
        "x.spec.ts": (
            "import { f } from '../src/f';\n"
            "describe('f', () => {\n"
            "    it('works', () => {\n"
            "        expect(f()).toBe(1);\n"
            "    });\n"
            "});\n"
        ),
    }
    assert specops_cli._check_typescript_syntax(files) == []


def test_check_typescript_syntax_skips_when_no_ts_files():
    assert specops_cli._check_typescript_syntax({"a.py": "x = 1"}) == []


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
    monkeypatch.setattr(specops_cli.certificate, "generate", lambda f: f"certificates/CHG-0001-{f}.md")

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
    # two commits: the patch itself, then the certificate follow-up
    assert sum(1 for c in calls if c[:2] == ["git", "commit"]) == 2
    assert any(c == ["git", "add", f"certificates/CHG-0001-{feature}.md"] for c in calls)
    assert StateMachine().load(feature)["stage"] == "APPLIED"


def test_apply_only_stages_the_patchs_own_files_not_unrelated_work(monkeypatch):
    feature = "scoped-feature"
    os.makedirs("out", exist_ok=True)
    with open(f"out/{feature}.patch", "w") as f:
        f.write(
            "diff --git a/new_thing.py b/new_thing.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/new_thing.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+x = 1\n"
        )
    # simulate unrelated work-in-progress sitting uncommitted elsewhere
    with open("some_other_file.py", "w") as f:
        f.write("# unrelated, mid-edit, not part of this feature\n")
    StateMachine().advance(feature, APPLY_PENDING)

    monkeypatch.setattr("builtins.input", lambda _: "yes")
    monkeypatch.setattr(specops_cli.certificate, "generate", lambda f: f"certificates/CHG-0001-{f}.md")

    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=1, stdout="main\n")

    monkeypatch.setattr(specops_cli.subprocess, "run", fake_run)

    specops_cli.cmd_apply(Namespace(feature=feature))

    add_calls = [c for c in calls if c[:2] == ["git", "add"] and "new_thing.py" in c]
    assert len(add_calls) == 1
    assert "some_other_file.py" not in add_calls[0]
    assert "." not in add_calls[0]


def test_apply_replaces_stale_branch_from_a_previous_apply(monkeypatch):
    feature = "redo-feature"
    _write_patch(feature)
    StateMachine().advance(feature, APPLY_PENDING)

    monkeypatch.setattr("builtins.input", lambda _: "yes")
    monkeypatch.setattr(specops_cli.certificate, "generate", lambda f: f"certificates/CHG-0001-{f}.md")

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
