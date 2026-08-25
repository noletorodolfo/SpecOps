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
    os.makedirs(".specops/out", exist_ok=True)
    with open(f".specops/out/{feature}.patch", "w") as f:
        f.write("diff --git a/x b/x\n")


def test_check_python_syntax_flags_squashed_lines():
    # A file can be a clean, applicable diff and still be broken code —
    # e.g. a model joining two logical lines onto one. The diff is
    # generated deterministically now, but nothing about that makes the
    # *content* valid, so this gate still matters.
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
    monkeypatch.setattr(specops_cli.certificate, "generate", lambda f: f".specops/certificates/CHG-0001-{f}.md")

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
    assert any(c == ["git", "add", f".specops/certificates/CHG-0001-{feature}.md"] for c in calls)
    assert StateMachine().load(feature)["stage"] == "APPLIED"


def test_apply_only_stages_the_patchs_own_files_not_unrelated_work(monkeypatch):
    feature = "scoped-feature"
    os.makedirs(".specops/out", exist_ok=True)
    with open(f".specops/out/{feature}.patch", "w") as f:
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
    monkeypatch.setattr(specops_cli.certificate, "generate", lambda f: f".specops/certificates/CHG-0001-{f}.md")

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
    monkeypatch.setattr(specops_cli.certificate, "generate", lambda f: f".specops/certificates/CHG-0001-{f}.md")

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


def _stub_work_phase(monkeypatch, response_text):
    """Drive cmd_work with a canned model response, skipping prompt
    building and the network entirely."""
    monkeypatch.setattr(
        specops_cli,
        "build_prompt",
        lambda *a, **k: {"prompt_text": "x", "prompt_hash": "h", "rag_sources": []},
    )
    monkeypatch.setattr(
        specops_cli,
        "get_send_prompt",
        lambda: (lambda prompt, ctx: {"response_text": response_text, "model": "stub"}),
    )


def _init_git_project(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    os.makedirs(".specops/plans/f", exist_ok=True)
    with open(".specops/plans/f/plan.yaml", "w") as fh:
        fh.write("do the thing\n")


def test_work_creates_a_new_file_from_model_output(tmp_path, monkeypatch):
    _init_git_project(tmp_path)
    _stub_work_phase(
        monkeypatch,
        "<<<SPECOPS_FILE hello.py>>>\ndef hi():\n    return 1\n<<<SPECOPS_END>>>\n",
    )

    specops_cli.cmd_work(Namespace(feature="f", plan="", file=[]))

    patch = open(".specops/out/f.patch").read()
    assert "new file mode" in patch
    assert "+def hi():" in patch
    assert StateMachine().load("f")["stage"] == REVIEW_PATCH


def test_work_can_now_modify_an_existing_file(tmp_path, monkeypatch):
    _init_git_project(tmp_path)
    with open("existing.py", "w") as fh:
        fh.write("def hi():\n    return 1\n")

    _stub_work_phase(
        monkeypatch,
        "<<<SPECOPS_FILE existing.py>>>\ndef hi():\n    return 2\n<<<SPECOPS_END>>>\n",
    )

    specops_cli.cmd_work(Namespace(feature="f", plan="", file=["existing.py"]))

    patch = open(".specops/out/f.patch").read()
    assert "new file mode" not in patch, "modifying a file must not be a creation"
    assert "-    return 1" in patch
    assert "+    return 2" in patch
    assert StateMachine().load("f")["stage"] == REVIEW_PATCH


def test_work_refuses_a_rewrite_that_dropped_most_of_the_file(tmp_path, monkeypatch):
    _init_git_project(tmp_path)
    with open("big.py", "w") as fh:
        fh.write("\n".join(f"line{i} = {i}" for i in range(30)) + "\n")

    _stub_work_phase(
        monkeypatch,
        "<<<SPECOPS_FILE big.py>>>\nline0 = 0\n<<<SPECOPS_END>>>\n",
    )

    with pytest.raises(SystemExit):
        specops_cli.cmd_work(Namespace(feature="f", plan="", file=["big.py"]))

    assert StateMachine().load("f")["stage"] == WORK_DRAFT
    assert open("big.py").read().count("\n") == 30, "the file must be left untouched"


def test_work_rejects_a_path_escaping_the_project(tmp_path, monkeypatch):
    _init_git_project(tmp_path)
    _stub_work_phase(
        monkeypatch,
        "<<<SPECOPS_FILE ../escaped.py>>>\nx = 1\n<<<SPECOPS_END>>>\n",
    )

    with pytest.raises(SystemExit):
        specops_cli.cmd_work(Namespace(feature="f", plan="", file=[]))

    assert StateMachine().load("f")["stage"] == WORK_DRAFT
    assert not os.path.exists(tmp_path.parent / "escaped.py")


def test_work_rejects_broken_python_before_review(tmp_path, monkeypatch):
    _init_git_project(tmp_path)
    _stub_work_phase(
        monkeypatch,
        "<<<SPECOPS_FILE broken.py>>>\ndef f(:\n    pass\n<<<SPECOPS_END>>>\n",
    )

    with pytest.raises(SystemExit):
        specops_cli.cmd_work(Namespace(feature="f", plan="", file=[]))

    assert StateMachine().load("f")["stage"] == WORK_DRAFT


def test_work_refuses_to_rewrite_a_file_it_was_not_shown_in_full(tmp_path, monkeypatch):
    """Retrieval puts *excerpts* of files in the prompt. If the model
    then emits one of those as a full file, everything it didn't see
    would be silently deleted — so that must be refused outright."""
    _init_git_project(tmp_path)
    with open("untouched.py", "w") as fh:
        fh.write("def a():\n    return 1\n\n\ndef b():\n    return 2\n")

    # the model answers with a file it was never given in full
    _stub_work_phase(
        monkeypatch,
        "<<<SPECOPS_FILE untouched.py>>>\ndef a():\n    return 99\n<<<SPECOPS_END>>>\n",
    )

    with pytest.raises(SystemExit):
        specops_cli.cmd_work(Namespace(feature="f", plan="", file=[]))

    assert StateMachine().load("f")["stage"] == WORK_DRAFT
    assert "def b():" in open("untouched.py").read(), "the file must be untouched"


def test_work_allows_rewriting_a_file_provided_in_full(tmp_path, monkeypatch):
    """The mirror of the guard above: with --file, the same rewrite is
    allowed, because now the model actually saw what it's replacing."""
    _init_git_project(tmp_path)
    with open("shown.py", "w") as fh:
        fh.write("def a():\n    return 1\n")

    _stub_work_phase(
        monkeypatch,
        "<<<SPECOPS_FILE shown.py>>>\ndef a():\n    return 99\n<<<SPECOPS_END>>>\n",
    )

    specops_cli.cmd_work(Namespace(feature="f", plan="", file=["shown.py"]))

    assert StateMachine().load("f")["stage"] == REVIEW_PATCH
    assert "+    return 99" in open(".specops/out/f.patch").read()


def test_work_still_allows_creating_brand_new_files(tmp_path, monkeypatch):
    """The guard keys on existing-and-unseen, so a genuinely new file
    must still pass without needing --file."""
    _init_git_project(tmp_path)
    _stub_work_phase(
        monkeypatch,
        "<<<SPECOPS_FILE fresh.py>>>\nx = 1\n<<<SPECOPS_END>>>\n",
    )

    specops_cli.cmd_work(Namespace(feature="f", plan="", file=[]))

    assert StateMachine().load("f")["stage"] == REVIEW_PATCH


def test_collect_existing_files_prefers_explicit_over_retrieved(tmp_path):
    for name in ("explicit.py", "mentioned.py", "retrieved.py"):
        with open(name, "w") as fh:
            fh.write("x = 1\n")

    collected = specops_cli._collect_existing_files(
        ["the plan mentions mentioned.py"],
        explicit_paths=["explicit.py"],
        extra_paths=["retrieved.py"],
    )

    assert list(collected) == ["explicit.py", "mentioned.py", "retrieved.py"]


def test_collect_existing_files_picks_up_paths_named_in_the_plan(tmp_path):
    with open("mentioned.py", "w") as fh:
        fh.write("x = 1\n")

    collected = specops_cli._collect_existing_files(
        ["the plan says to update mentioned.py and also missing.py"]
    )

    assert "mentioned.py" in collected
    assert "missing.py" not in collected, "a file that doesn't exist can't be context"


def test_collect_existing_files_never_feeds_back_specops_internals(tmp_path):
    os.makedirs(".specops/specs", exist_ok=True)
    with open(".specops/specs/x.md", "w") as fh:
        fh.write("spec text\n")

    collected = specops_cli._collect_existing_files(["see .specops/specs/x.md"])

    assert collected == {}


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
