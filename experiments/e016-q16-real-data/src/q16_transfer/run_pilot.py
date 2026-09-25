"""Configured entry point. No arguments; missing certification produces no score."""
import json
from decimal import InvalidOperation
import platform
import time
from pathlib import Path

from adapter import adapt_episode
from admission import AdmissionBlocked, load_admitted
from core import StateCapExceeded

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "pilot_result.json"


def main():
    started = time.monotonic()
    result = {"task": "T-009", "experiment": "E-016", "seed": 20260919,
              "python": platform.python_version(), "real_replication_completed": False}
    try:
        config = json.loads((HERE / "pilot_config.json").read_text())
        if config.get("seed") != 20260919 or config.get("state_cap") != 100000:
            raise AdmissionBlocked("Frozen seed/state cap altered; protocol review required")
        contract, episodes = load_admitted(config)
    except (AdmissionBlocked, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        result.update(status="blocked", reason=str(exc), scored_real_episodes=0)
    else:
        rows = []
        for episode in episodes:
            try:
                rows.append(adapt_episode(episode, contract["quantity_quantum"], config["state_cap"]))
            except StateCapExceeded as exc:
                rows.append({"episode_id": episode["episode_id"], "status": "state_cap", "reason": str(exc)})
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                rows.append({"episode_id": episode.get("episode_id"), "status": "invalid", "reason": str(exc)})
        invalid = any(row["status"] == "invalid" for row in rows)
        # A conservation failure invalidates the batch; do not rescue its convenient rows.
        result.update(status="invalid_batch" if invalid else "development_pilot_only",
                      scored_real_episodes=0 if invalid else sum(row["status"] == "scored" for row in rows),
                      outcomes=[] if invalid else rows,
                      audit_rows=rows if invalid else [],
                      attempted_episodes=len(episodes), contract_version=contract["version"])
    result["seconds"] = time.monotonic() - started
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
