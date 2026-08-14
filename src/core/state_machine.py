import json, os, time

STATE_DIR = "state"

# Ordered pipeline stages. apply is only allowed once a feature reaches APPLY_PENDING.
SPEC_DRAFT = "SPEC_DRAFT"
PLAN_DRAFT = "PLAN_DRAFT"
WORK_DRAFT = "WORK_DRAFT"
REVIEW_PATCH = "REVIEW_PATCH"
APPLY_PENDING = "APPLY_PENDING"
APPLIED = "APPLIED"


class StateMachine:
    def __init__(self):
        pass

    def save(self, feature, state):
        os.makedirs(STATE_DIR, exist_ok=True)
        path = f"{STATE_DIR}/{feature}.json"
        with open(path, "w") as f:
            json.dump(state, f, indent=2)

    def load(self, feature):
        path = f"{STATE_DIR}/{feature}.json"
        if not os.path.exists(path):
            return {}
        return json.load(open(path))

    def advance(self, feature, stage, **extra):
        state = self.load(feature)
        state.update(extra)
        state["stage"] = stage
        state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.save(feature, state)
        return state

