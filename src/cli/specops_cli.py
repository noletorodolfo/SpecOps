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
    context = {"feature": feature, "spec_file": args.spec}
    prompt_meta = build_prompt("plan", "default", context, "")
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
    context = {"feature": feature, "plan_file": args.plan}
    prompt_meta = build_prompt("work", "default", context, "")
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("WORK", prompt_meta, resp, status=WORK_DRAFT)
    os.makedirs("out", exist_ok=True)
    patch_path = f"out/{feature}.patch"
    with open(patch_path, "w") as f:
        f.write(resp["response_text"])

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
    existing = subprocess.run(
        ["git", "rev-parse", "--verify", branch], capture_output=True
    )
    if existing.returncode == 0:
        subprocess.run(["git", "checkout", branch], check=True)
    else:
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
