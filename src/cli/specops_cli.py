#!/usr/bin/env python3
import argparse
import os
from core.prompt_builder import build_prompt
from adapters.adapter_mock import send_prompt as mock_send
from core.state_machine import StateMachine
from core.logger import audit_log

SM = StateMachine()

def cmd_brainstorm(args):
    context = {"feature": args.feature}
    prompt_meta = build_prompt("spec", "default", context, args.notes or "")
    resp = mock_send(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("SPEC", prompt_meta, resp)
    os.makedirs("specs", exist_ok=True)
    path = f"specs/{args.feature}.md"
    with open(path, "w") as f:
        f.write(resp["response_text"])
    print(f"Wrote {path}")

def cmd_plan(args):
    context = {"feature": args.feature, "spec_file": args.spec}
    prompt_meta = build_prompt("plan", "default", context, "")
    resp = mock_send(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("PLAN", prompt_meta, resp)
    path = f"plans/{args.feature}/plan.yaml"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(resp["response_text"])
    print(f"Wrote {path}")

def cmd_work(args):
    context = {"feature": args.feature, "plan_file": args.plan}
    prompt_meta = build_prompt("work", "default", context, "")
    resp = mock_send(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("WORK", prompt_meta, resp)
    os.makedirs("out", exist_ok=True)
    patch_path = f"out/{args.feature}.patch"
    with open(patch_path, "w") as f:
        f.write(resp["response_text"])
    print(f"Patch generated: {patch_path}")

def cmd_review(args):
    print("Running review (validators)...")
    os.system("bash tools/validators.sh")

def cmd_apply(args):
    patch_path = f"out/{args.feature}.patch"
    if not os.path.exists(patch_path):
        print("Patch not found:", patch_path); return
    confirm = input(f"Apply patch {patch_path}? Type 'yes' to proceed: ")
    if confirm.strip().lower() != "yes":
        print("Aborted by user.")
        return
    os.system(f"git checkout -b feat/{args.feature} || true")
    os.system(f"git apply {patch_path}")
    os.system("git add . && git commit -m \"specops: apply patch\"")
    print("Patch applied and committed on new branch.")

def main():
    p = argparse.ArgumentParser(prog="specops")
    sub = p.add_subparsers(dest="cmd")
    b = sub.add_parser("brainstorm"); b.add_argument("feature"); b.add_argument("--notes")
    pl = sub.add_parser("plan"); pl.add_argument("feature"); pl.add_argument("--spec", default="")
    w = sub.add_parser("work"); w.add_argument("feature"); w.add_argument("--plan", default="")
    r = sub.add_parser("review"); r.add_argument("feature", nargs="?")
    a = sub.add_parser("apply"); a.add_argument("feature")
    args = p.parse_args()
    if args.cmd == "brainstorm": cmd_brainstorm(args)
    elif args.cmd == "plan": cmd_plan(args)
    elif args.cmd == "work": cmd_work(args)
    elif args.cmd == "review": cmd_review(args)
    elif args.cmd == "apply": cmd_apply(args)
    else: p.print_help()

if __name__ == "__main__":
    main()

