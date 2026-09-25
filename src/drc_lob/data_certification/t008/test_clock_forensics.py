"""Semantic guard cases for distinguishing conditional acceptance from book insertion."""
import json
import tempfile
from pathlib import Path
from clock_forensics import visible_insertion_candidates


def status(sid, stamp, trigger=False, tif=1):
    return dict(status_id=sid, timestamp_ns=stamp, is_trigger=trigger, tif_id=tif)


cases = [
    ("delayed_stop_limit_uses_trigger_not_acceptance", [status(1, 100, True, 3), status(9, 300, True, 3)], [300]),
    ("untriggered_conditional_acceptance_is_not_visible", [status(1, 100, True, 3)], []),
    ("ioc_acceptance_is_not_a_resting_insertion", [status(1, 100, False, 2)], []),
    ("ordinary_resting_open_is_visible", [status(1, 100)], [100]),
    ("triggered_label_without_trigger_flag_is_not_sufficient", [status(9, 300)], []),
    ("ambiguous_trigger_times_are_preserved", [status(9, 300, True), status(9, 400, True)], [300, 400]),
]
results = []
for name, rows, expected in cases:
    actual = visible_insertion_candidates(rows)
    assert actual == expected, (name, expected, actual)
    results.append(dict(name=name, passed=True, expected_ns=expected, actual_ns=actual))
with tempfile.TemporaryDirectory() as directory:
    out = Path(directory) / "clock_adversarial_tests.json"
    out.write_text(json.dumps(dict(cases=results, passed=len(results)), indent=2) + "\n")
    assert json.loads(out.read_text())["passed"] == len(results)
print(f"{len(results)} semantic clock guard cases passed")
