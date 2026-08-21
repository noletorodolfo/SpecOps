#!/usr/bin/env python3
import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
from dotenv import load_dotenv

load_dotenv()

from core.prompt_builder import build_prompt
from adapters import get_send_prompt
from core.state_machine import (
    StateMachine,
    SPEC_DRAFT,
    PLAN_DRAFT,
    WORK_DRAFT,
    REVIEW_PATCH,
    APPLY_PENDING,
    APPLIED,
)
from core.logger import audit_log
from core import certificate
from core import project as project_mod

SM = StateMachine()
FEATURE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_feature(feature):
    if not FEATURE_RE.match(feature):
        raise SystemExit(
            f"Invalid feature name '{feature}': only letters, digits, '-' and '_' are allowed."
        )
    return feature


DIFF_FENCE_RE = re.compile(r"^```(?:diff|patch)?\s*\n(.*)\n```\s*$", re.DOTALL)
DIFF_HEADER_PREFIXES = (
    "diff --git ", "index ", "--- ", "+++ ", "@@ ",
    "new file mode", "deleted file mode", "similarity index",
    "rename from", "rename to", "Binary files",
)


def _repair_missing_plus_prefix(text):
    """Small models routinely get the diff headers right but forget that
    every content line inside a hunk must start with '+'/'-'/' ' — they
    just paste the raw file content instead. This is most dangerous in a
    new-file hunk (--- /dev/null): a content line that happens to start
    with a space, like ordinary Python indentation, looks exactly like a
    valid diff *context* marker — except new-file hunks can't have
    context lines at all, every line there is an addition, so the usual
    "leave lines starting with ' ' alone" heuristic would silently corrupt
    indented code. Track whether we're in a new-file hunk and, if so,
    require every line to start with '+' with no exceptions."""
    lines = text.split("\n")
    out = []
    in_hunk = False
    is_new_file = False
    for line in lines:
        if line.startswith(DIFF_HEADER_PREFIXES):
            if line.startswith("--- "):
                is_new_file = line.strip() == "--- /dev/null"
            in_hunk = line.startswith("@@ ")
            out.append(line)
        elif not in_hunk:
            out.append(line)
        elif line.startswith("\\ "):
            # The "\ No newline at end of file" annotation is not a
            # content line and must never get a '+' — it stands alone.
            out.append(line)
        elif line.startswith("++"):
            # A diff marker is exactly one character; models occasionally
            # double it up on one line ("++foo" instead of "+foo"). Drop
            # exactly one extra leading '+', not a full lstrip, so content
            # that itself starts with '+' (e.g. "+= 1") is left intact.
            out.append(line[1:])
        elif line.startswith("+"):
            out.append(line)
        elif is_new_file or line[:1] not in ("-", " "):
            out.append("+" + line)
        else:
            out.append(line)
    return "\n".join(out)


HUNK_HEADER_RE = re.compile(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$")


def _repair_new_file_hunk_count(text):
    """For a single new-file hunk (@@ -0,0 +N,M @@), the model frequently
    invents a wrong M. Recompute it from the actual number of '+' lines
    that follow, since `git apply` rejects a mismatched count outright."""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HUNK_HEADER_RE.match(line)
        if m and m.group(1) == "0" and m.group(2) == "0":
            body = []
            j = i + 1
            while j < len(lines) and not lines[j].startswith(DIFF_HEADER_PREFIXES):
                body.append(lines[j])
                j += 1
            plus_count = sum(1 for l in body if l.startswith("+"))
            out.append(f"@@ -0,0 +{m.group(3)},{plus_count} @@{m.group(5)}")
            out.extend(body)
            i = j
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _repair_missing_hunk_header(text):
    """A model occasionally omits the '@@ -0,0 +1,N @@' hunk header
    entirely for a new file, jumping straight from '+++ b/<path>' to the
    content lines. `git apply --check` tolerates this — it's lenient
    about the header — but actually applying it then produces an EMPTY
    file, since git has no line-count info to work from. Insert a
    synthesized header (the exact count gets recomputed precisely by
    _repair_new_file_hunk_count right after this runs)."""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if line.startswith("+++ ") and (
            i + 1 >= len(lines) or not lines[i + 1].startswith("@@ ")
        ):
            count = 0
            j = i + 1
            while j < len(lines) and not lines[j].startswith(DIFF_HEADER_PREFIXES):
                count += 1
                j += 1
            out.append(f"@@ -0,0 +1,{count} @@")
        i += 1
    return "\n".join(out)


def clean_diff_output(text):
    """Real models routinely wrap a diff in a markdown code fence despite
    being told not to, omit the hunk header, forget the leading '+' on
    content lines, or write a hunk header with the wrong line count.
    Repair all four, since `git apply` is strict about each — and some
    failures (missing header) only show up as silently empty files once
    actually applied, not as an error `git apply --check` catches."""
    text = text.strip()
    fence = DIFF_FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    text = _repair_missing_hunk_header(text)
    text = _repair_missing_plus_prefix(text)
    text = _repair_new_file_hunk_count(text)
    return text + "\n"


NEW_FILE_PATH_RE = re.compile(r"^\+\+\+ b/(.+)$")


def _extract_new_file_contents(text):
    """Reconstruct each new file's final content directly from an
    already-repaired diff, without touching the working tree. Used to run
    language-specific checks (e.g. Python syntax) before the patch is even
    applied — `git apply --check` only validates diff *mechanics*, it has
    no idea whether the resulting file is valid code."""
    files = {}
    current_path = None
    content_lines = []
    for line in text.split("\n"):
        m = NEW_FILE_PATH_RE.match(line)
        if m:
            if current_path is not None:
                files[current_path] = "\n".join(content_lines)
            current_path = m.group(1)
            content_lines = []
        elif (
            current_path is not None
            and not line.startswith("@@ ")
            and line.startswith(DIFF_HEADER_PREFIXES)
        ):
            files[current_path] = "\n".join(content_lines)
            current_path = None
            content_lines = []
        elif current_path is not None and line.startswith("+"):
            content_lines.append(line[1:])
        # non-'+' lines inside a hunk body (e.g. the no-newline marker)
        # aren't part of the file's actual content, so they're skipped.
    if current_path is not None:
        files[current_path] = "\n".join(content_lines)
    return files


def _check_python_syntax(files):
    errors = []
    for path, content in files.items():
        if not path.endswith(".py"):
            continue
        try:
            ast.parse(content)
        except SyntaxError as exc:
            errors.append(f"{path}:{exc.lineno}: {exc.msg}")
    return errors


# The SpecOps engine's own install location (where this file lives), as
# opposed to whatever project it's currently operating on — tools/ (and
# its jest/ts-jest setup) belong to the engine, not to each project.
ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TS_CHECKER = os.path.join(ENGINE_ROOT, "tools", "ts_syntax_check.mjs")
VALIDATORS_SH = os.path.join(ENGINE_ROOT, "tools", "validators.sh")


def _check_typescript_syntax(files):
    """Same idea as _check_python_syntax, for .ts/.tsx files: syntax only,
    via the TypeScript compiler's parser (tools/ts_syntax_check.mjs) — not
    full type-checking, which would need the file's imports and any
    @types packages (jest, etc.) to actually resolve and would false-flag
    perfectly valid generated code."""
    ts_files = {p: c for p, c in files.items() if p.endswith((".ts", ".tsx"))}
    if not ts_files:
        return []
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        return []  # node not available in this environment; skip rather than block

    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        for path, content in ts_files.items():
            # Keep the real extension so the checker parses TSX correctly;
            # the rest of the name/path doesn't matter, it's a scratch copy.
            suffix = ".tsx" if path.endswith(".tsx") else ".ts"
            tmp_path = os.path.join(tmp, f"check{suffix}")
            with open(tmp_path, "w") as f:
                f.write(content)
            result = subprocess.run(
                ["node", TS_CHECKER, tmp_path], capture_output=True, text=True
            )
            if result.returncode != 0:
                errors.append(f"{path}: {result.stderr.strip().replace(tmp_path, path)}")
    return errors


def cmd_brainstorm(args):
    feature = validate_feature(args.feature)
    context = {"feature": feature}
    prompt_meta = build_prompt("spec", "default", context, args.notes or "")
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("SPEC", prompt_meta, resp, status=SPEC_DRAFT)
    os.makedirs(".specops/specs", exist_ok=True)
    path = f".specops/specs/{feature}.md"
    with open(path, "w") as f:
        f.write(resp["response_text"])
    SM.advance(feature, SPEC_DRAFT)
    print(f"Wrote {path}")


def cmd_plan(args):
    feature = validate_feature(args.feature)
    spec_path = args.spec or f".specops/specs/{feature}.md"
    spec_content = ""
    if os.path.exists(spec_path):
        with open(spec_path) as f:
            spec_content = f.read()
    context = {"feature": feature, "spec_file": spec_path}
    prompt_meta = build_prompt("plan", "default", context, spec_content)
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("PLAN", prompt_meta, resp, status=PLAN_DRAFT)
    path = f".specops/plans/{feature}/plan.yaml"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(resp["response_text"])
    SM.advance(feature, PLAN_DRAFT)
    print(f"Wrote {path}")


def cmd_work(args):
    feature = validate_feature(args.feature)
    plan_path = args.plan or f".specops/plans/{feature}/plan.yaml"
    plan_content = ""
    if os.path.exists(plan_path):
        with open(plan_path) as f:
            plan_content = f.read()
    context = {"feature": feature, "plan_file": plan_path}
    prompt_meta = build_prompt("work", "default", context, plan_content)
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("WORK", prompt_meta, resp, status=WORK_DRAFT)
    os.makedirs(".specops/out", exist_ok=True)
    patch_path = f".specops/out/{feature}.patch"
    cleaned = clean_diff_output(resp["response_text"])
    with open(patch_path, "w") as f:
        f.write(cleaned)

    # Catch malformed diffs (mock placeholder text, model hallucination,
    # truncated output) right away, instead of only discovering it when
    # 'apply' tries to use the patch after review already passed.
    check = subprocess.run(
        ["git", "apply", "--check", patch_path], capture_output=True, text=True
    )
    if check.returncode != 0:
        SM.advance(feature, WORK_DRAFT)
        print(f"Generated output is not a valid git diff: {patch_path}")
        print(check.stderr.strip())
        print("State: WORK_DRAFT. Fix the prompt/model output and re-run 'specops work'.")
        raise SystemExit(1)

    # `git apply --check` only validates diff *mechanics* — it has no idea
    # whether the resulting file is valid code. Models occasionally squash
    # what should be separate lines onto one physical line (using a literal
    # ' +' instead of a real newline+marker), which still parses as a
    # structurally valid diff but produces broken source. Catch that here,
    # for Python files, before it ever reaches review.
    new_files = _extract_new_file_contents(cleaned)
    syntax_errors = _check_python_syntax(new_files) + _check_typescript_syntax(new_files)
    if syntax_errors:
        SM.advance(feature, WORK_DRAFT)
        print(f"Generated file(s) failed a syntax check: {patch_path}")
        for err in syntax_errors:
            print(f"  {err}")
        print("State: WORK_DRAFT. Fix the prompt/model output and re-run 'specops work'.")
        raise SystemExit(1)

    # A patch was generated and is structurally valid, but not yet reviewed:
    # it must pass 'specops review' before it becomes eligible for apply.
    SM.advance(feature, REVIEW_PATCH)
    print(f"Patch generated: {patch_path}")
    print("State: REVIEW_PATCH. Run 'specops review <feature>' before apply.")


def cmd_review(args):
    feature = validate_feature(args.feature) if args.feature else None
    print("Running review (validators)...")
    # Ensure venv-only tools (e.g. pytest) resolve even when this process was
    # launched via the venv's console-script entrypoint (e.g. from Neovim)
    # without the venv being activated in the caller's shell.
    env = os.environ.copy()
    venv_bin = os.path.dirname(sys.executable)
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    # validators.sh lives in the engine, not the project, and needs to know
    # where to find its own jest/ts-jest install regardless of which
    # project's directory it's actually validating.
    env["SPECOPS_ENGINE_ROOT"] = ENGINE_ROOT
    result = subprocess.run(["bash", VALIDATORS_SH], env=env)
    passed = result.returncode == 0
    if feature:
        state = SM.advance(feature, APPLY_PENDING if passed else WORK_DRAFT)
        prompt_meta = {"prompt_hash": "n/a", "rag_sources": []}
        resp = {"response_text": "", "model": "n/a"}
        audit_log(
            "REVIEW",
            prompt_meta,
            resp,
            validators_run=["tools/validators.sh"],
            status=state["stage"],
            feature=feature,
        )
        if passed:
            print(f"Review passed. State: APPLY_PENDING.")
        else:
            print(f"Review failed. State reset to WORK_DRAFT — fix and re-run work/review.")
    if not passed:
        raise SystemExit(1)


def cmd_apply(args):
    feature = validate_feature(args.feature)
    patch_path = f".specops/out/{feature}.patch"
    if not os.path.exists(patch_path):
        print("Patch not found:", patch_path)
        return

    state = SM.load(feature)
    if state.get("stage") != APPLY_PENDING:
        print(
            f"Cannot apply: feature '{feature}' is in stage "
            f"'{state.get('stage', 'UNKNOWN')}', expected APPLY_PENDING. "
            "Run 'specops review <feature>' and ensure it passes first."
        )
        raise SystemExit(1)

    confirm = input(f"Apply patch {patch_path}? Type 'yes' to proceed: ")
    if confirm.strip().lower() != "yes":
        print("Aborted by user.")
        return

    branch = f"feat/{feature}"
    current_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    if current_branch != branch:
        exists = (
            subprocess.run(["git", "rev-parse", "--verify", branch], capture_output=True).returncode
            == 0
        )
        if exists:
            # A previous apply already used this branch name. Each apply is a
            # fresh attempt against regenerated spec/plan/patch content, so
            # start the branch over from the current commit instead of
            # reusing stale history — reusing it via a plain checkout also
            # fails outright whenever freshly regenerated (untracked) specs
            # or plans collide with what that old branch already tracked.
            subprocess.run(["git", "branch", "-D", branch], check=True)
        subprocess.run(["git", "checkout", "-b", branch], check=True)

    try:
        subprocess.run(["git", "apply", patch_path], check=True)
        with open(patch_path) as f:
            patch_content = f.read()
        # Stage only what this feature actually touches — the patch's own
        # new files plus its spec artifact — never `git add .`. A blanket
        # add would sweep in any unrelated work-in-progress sitting
        # uncommitted elsewhere in the working tree into this feature's
        # commit, silently mixing unrelated changes together. plans/ and
        # out/ are gitignored on purpose (ephemeral working files) and stay
        # that way — only specs/ was ever meant to be part of the record.
        files_to_add = list(_extract_new_file_contents(patch_content).keys())
        spec_path = f".specops/specs/{feature}.md"
        if os.path.exists(spec_path):
            files_to_add.append(spec_path)
        subprocess.run(["git", "add", *files_to_add], check=True)
        subprocess.run(["git", "commit", "-m", "specops: apply patch"], check=True)
    except subprocess.CalledProcessError as exc:
        print(
            f"Apply failed on branch '{branch}': {exc}. "
            "The patch was not applied; fix it (or regenerate with 'specops work') "
            "and re-run review before trying apply again."
        )
        raise SystemExit(1)

    SM.advance(feature, APPLIED)
    print("Patch applied and committed on new branch.")

    # Generated after the commit exists, since it records that commit's own
    # SHA — so it lands in its own small follow-up commit rather than the
    # code-change commit itself.
    cert_path = certificate.generate(feature)
    subprocess.run(["git", "add", cert_path], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"specops: add change certificate for {feature}"],
        check=True,
    )
    print(f"Change certificate: {cert_path}")


def cmd_project_init(args):
    specops_dir, already_existed = project_mod.init_project(args.path or os.getcwd())
    if already_existed:
        print(f"Already initialized: {specops_dir}")
    else:
        print(f"Initialized {specops_dir}")
        print("Edit governance.yml to match this project, then add notes under rags/.")


def main():
    p = argparse.ArgumentParser(prog="specops")
    p.add_argument(
        "--project",
        default=None,
        help="Path to the project to operate on. Defaults to discovering a "
        ".specops/ directory starting from the current directory and "
        "walking up, the same way git looks for .git/.",
    )
    sub = p.add_subparsers(dest="cmd")
    b = sub.add_parser("brainstorm")
    b.add_argument("feature")
    b.add_argument("--notes")
    pl = sub.add_parser("plan")
    pl.add_argument("feature")
    pl.add_argument("--spec", default="")
    w = sub.add_parser("work")
    w.add_argument("feature")
    w.add_argument("--plan", default="")
    r = sub.add_parser("review")
    r.add_argument("feature", nargs="?")
    a = sub.add_parser("apply")
    a.add_argument("feature")
    proj = sub.add_parser("project")
    proj_sub = proj.add_subparsers(dest="project_cmd")
    proj_init = proj_sub.add_parser("init")
    proj_init.add_argument("path", nargs="?", default=None)

    args = p.parse_args()

    if args.cmd == "project":
        if args.project_cmd == "init":
            cmd_project_init(args)
        else:
            proj.print_help()
        return

    if args.cmd is None:
        p.print_help()
        return

    root = project_mod.find_project_root(explicit=args.project)
    os.chdir(root)

    if args.cmd == "brainstorm":
        cmd_brainstorm(args)
    elif args.cmd == "plan":
        cmd_plan(args)
    elif args.cmd == "work":
        cmd_work(args)
    elif args.cmd == "review":
        cmd_review(args)
    elif args.cmd == "apply":
        cmd_apply(args)


if __name__ == "__main__":
    main()
