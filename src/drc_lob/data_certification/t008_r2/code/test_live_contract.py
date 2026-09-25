"""Exercise capture boundary semantics without a market connection."""
import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import live_snapshot_contract as normalizer


class LiveContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("data", "evidence"):
            (self.root / directory).mkdir()
        (self.root / "evidence/live_capture_status.json").write_text('{"status":"completed"}')
        self.previous = normalizer.CAPTURE_ROOT, normalizer.OUT
        normalizer.CAPTURE_ROOT, normalizer.OUT = self.root, self.root / "out"
        self.records = []
        for ordinal, second in enumerate(range(0, 301, 5)):
            data = {"coin": "BTC", "time": 1764547200000 + second * 1000,
                    "levels": [[{"px": str(1000 - i), "sz": "0.01", "n": 1} for i in range(20)],
                               [{"px": str(1001 + i), "sz": "0.01", "n": 1} for i in range(20)]]}
            self.records.append({"source_row_zero_based": ordinal, "connection_id": 1,
                "received_wall_ns": data["time"] * 1000000 + 100000000,
                "received_monotonic_ns": second * 1000000000,
                "wire_text": json.dumps({"channel": "l2Book", "data": data})})

    def tearDown(self):
        normalizer.CAPTURE_ROOT, normalizer.OUT = self.previous
        self.temporary.cleanup()

    def run_capture(self):
        status_path = self.root / "evidence/live_capture_status.json"
        status = json.loads(status_path.read_text())
        status.setdefault("wire_text_sha256_so_far", hashlib.sha256("".join(r["wire_text"] for r in self.records).encode()).hexdigest())
        status.setdefault("messages", len(self.records))
        status_path.write_text(json.dumps(status))
        with gzip.open(self.root / "data/live_capture.jsonl.gz", "wt") as stream:
            for record in self.records:
                stream.write(json.dumps(record) + "\n")
        with contextlib.redirect_stdout(io.StringIO()):
            normalizer.main()
        return json.loads((normalizer.OUT / "shared_data_contract.live.v2.0.0.json").read_text())

    def test_real_origin_preserved_receipt_not_admission(self):
        contract = self.run_capture()
        self.assertEqual(contract["origin"], "exploratory_real")
        self.assertEqual(len(contract["windows"]), 2)
        row = json.loads((normalizer.OUT / "btc_state_rows.jsonl").read_text().splitlines()[0])
        self.assertIsInstance(row["release_ns"], int)
        self.assertIsNone(row["admission_evidence_ns"])
        self.assertEqual(contract["scopes"]["Q16"]["decision"], "negative")

    def test_gap_segments_and_unchanged_duplicate(self):
        self.records.pop(30)
        duplicate = dict(self.records[-1])
        duplicate["source_row_zero_based"] += 1
        duplicate["received_wall_ns"] += 1
        self.records.append(duplicate)
        contract = self.run_capture()
        self.assertEqual(len(contract["windows"]), 4)
        stats = json.loads((normalizer.OUT / "diagnostics.json").read_text())
        self.assertEqual(stats["assets"]["BTC"]["gaps_over_policy"], 1)
        self.assertEqual(len(stats["duplicate_source_ordinals"]), 1)

    def test_conflicting_tie_rejected(self):
        duplicate = dict(self.records[-1])
        duplicate["source_row_zero_based"] += 1
        message = json.loads(duplicate["wire_text"])
        message["data"]["levels"][0][0]["sz"] = "0.02"
        duplicate["wire_text"] = json.dumps(message)
        self.records.append(duplicate)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.run_capture()

    def test_unclosed_capture_rejected(self):
        (self.root / "evidence/live_capture_status.json").write_text('{"status":"collecting"}')
        with self.assertRaisesRegex(ValueError, "closed capture"):
            self.run_capture()

    def test_acquisition_digest_tamper_rejected(self):
        (self.root / "evidence/live_capture_status.json").write_text(json.dumps({
            "status": "completed", "wire_text_sha256_so_far": "0" * 64}))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.run_capture()

    def test_acquisition_count_tamper_rejected(self):
        (self.root / "evidence/live_capture_status.json").write_text(json.dumps({
            "status": "completed", "messages": 1}))
        with self.assertRaisesRegex(ValueError, "message count mismatch"):
            self.run_capture()


if __name__ == "__main__":
    unittest.main()
