"""Execute private frozen source read-only and compare every information set.

Source path and seed are frozen. All generated files go to external artifacts.
This script contains no private source and does not copy it into the repository.
"""
import importlib.util
import json
from pathlib import Path
import time

from admission import sha256
from core import advance, initial_states, labels

TASK = (Path(__file__).resolve().parents[2] / 'runtime')
SOURCE = (Path(__file__).resolve().parents[2] / 'external' / 'q16' / 'count_probe.py')


def main():
    started = time.monotonic()
    spec = importlib.util.spec_from_file_location("frozen_count_probe", SOURCE)
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    source.P = TASK / "original_baseline"
    (source.P / "logs").mkdir(parents=True, exist_ok=True)
    source.run(seed=16029001, n=1000)
    baseline = json.loads((source.P / "logs" / "count_probe.json").read_text())
    checked = 0
    for record in baseline["records"]:
        queue = record["initial"][0]
        volume = initial_states(sum(q for q, tagged in queue if not tagged), 1)
        count = {s for s in volume if len(s.queue) == len(queue)}
        for event in record["events"]:
            kind, quantity = event["event"]
            volume = advance(volume, kind, quantity, probe_cancellable=False)
            count = advance(count, kind, quantity, probe_cancellable=False)
            count = {s for s in count if len(s.queue) == event["observed_count"]}
            if (labels(volume, 1)["any_fill"] != event["volume_only_fill_set"]
                    or labels(count, 1)["any_fill"] != event["count_fill_set"] or not count <= volume):
                raise ValueError(f"Parity failed at history {record['trial']} event {checked}")
            checked += 1
    result = {key: value for key, value in baseline.items() if key != "records"}
    result.update(source_file=str(SOURCE), source_sha256=sha256(SOURCE),
                  parity_observations=checked, parity_passed=True,
                  total_verification_seconds=time.monotonic() - started,
                  evidence_class="fresh synthetic source/software check; not a market replication")
    (TASK / "source_parity.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
