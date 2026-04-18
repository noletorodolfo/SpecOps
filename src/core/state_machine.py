import json, os
STATE_DIR = "state"
os.makedirs(STATE_DIR, exist_ok=True)

class StateMachine:
    def __init__(self):
        pass

    def save(self, feature, state):
        path = f"{STATE_DIR}/{feature}.json"
        with open(path, "w") as f:
            json.dump(state, f, indent=2)

    def load(self, feature):
        path = f"{STATE_DIR}/{feature}.json"
        if not os.path.exists(path): return {}
        return json.load(open(path))

