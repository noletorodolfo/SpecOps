#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys
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


def clean_diff_output(text):
    """Real models routinely wrap a diff in a markdown code fence despite
    being told not to, forget the leading '+' on content lines, or write
    a hunk header with the wrong line count. Repair all three, since
    `git apply` is strict about each."""
    text = text.strip()
    fence = DIFF_FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    text = _repair_missing_plus_prefix(text)
    text = _repair_new_file_hunk_count(text)
    return text + "\n"


def cmd_brainstorm(args):
    feature = validate_feature(args.feature)
    context = {"feature": feature}
    prompt_meta = build_prompt("spec", "default", context, args.notes or "")
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("SPEC", prompt_meta, resp, status=SPEC_DRAFT)
    os.makedirs("specs", exist_ok=True)
    path = f"specs/{feature}.md"
    with open(path, "w") as f:
        f.write(resp["response_text"])
    SM.advance(feature, SPEC_DRAFT)
    print(f"Wrote {path}")


def cmd_plan(args):
    feature = validate_feature(args.feature)
    spec_path = args.spec or f"specs/{feature}.md"
    spec_content = ""
    if os.path.exists(spec_path):
        with open(spec_path) as f:
            spec_content = f.read()
    context = {"feature": feature, "spec_file": spec_path}
    prompt_meta = build_prompt("plan", "default", context, spec_content)
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("PLAN", prompt_meta, resp, status=PLAN_DRAFT)
    path = f"plans/{feature}/plan.yaml"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(resp["response_text"])
    SM.advance(feature, PLAN_DRAFT)
    print(f"Wrote {path}")


def cmd_work(args):
    feature = validate_feature(args.feature)
    plan_path = args.plan or f"plans/{feature}/plan.yaml"
    plan_content = ""
    if os.path.exists(plan_path):
        with open(plan_path) as f:
            plan_content = f.read()
    context = {"feature": feature, "plan_file": plan_path}
    prompt_meta = build_prompt("work", "default", context, plan_content)
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("WORK", prompt_meta, resp, status=WORK_DRAFT)
    os.makedirs("out", exist_ok=True)
    patch_path = f"out/{feature}.patch"
    with open(patch_path, "w") as f:
        f.write(clean_diff_output(resp["response_text"]))

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
    result = subprocess.run(["bash", "tools/validators.sh"], env=env)
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
        )
        if passed:
            print(f"Review passed. State: APPLY_PENDING.")
        else:
            print(f"Review failed. State reset to WORK_DRAFT — fix and re-run work/review.")
    if not passed:
        raise SystemExit(1)


def cmd_apply(args):
    feature = validate_feature(args.feature)
    patch_path = f"out/{feature}.patch"
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
        subprocess.run(["git", "add", "."], check=True)
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


def main():
    p = argparse.ArgumentParser(prog="specops")
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
    args = p.parse_args()
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
    else:
        p.print_help()


if __name__ == "__main__":
    main()
