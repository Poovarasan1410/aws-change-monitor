import json
import os
from datetime import datetime, timezone


STATE_FILE = "data/state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "last_run": None,
            "processed": []
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return {
                "last_run": None,
                "processed": []
            }

        return json.loads(content)

    except json.JSONDecodeError:
        print("WARNING: state.json is invalid. Starting with empty state.")

        return {
            "last_run": None,
            "processed": []
        }


def save_state(state):
    os.makedirs("data", exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            indent=2
        )


def main():

    print("======================================")
    print("       AWS CHANGE MONITOR")
    print("======================================")

    state = load_state()

    print()
    print("Previous run:")
    print(state.get("last_run"))

    now = datetime.now(timezone.utc).isoformat()

    state["last_run"] = now

    save_state(state)

    print()
    print(f"Current run: {now}")
    print("Monitor executed successfully.")


if __name__ == "__main__":
    main()
