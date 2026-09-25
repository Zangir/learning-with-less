"""Independent fictional v2.2 evidence: hashes, origins and explicit disconnects."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from q18_adapter.contracts import sha256
from q18_adapter.paired_source import POLICY_SHA, STARTUP_POLICY_SHA, read_paired_contract, read_paired_rows


class PairedSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "contract.json"
        start = int(datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp()) * 10**9
        rows, provenance, lines = [], [], []
        for index in range(200):
            if index == 100:
                lines.append("")
            ordinal, event = len(lines), start + index * 10**9
            levels = [[{"px": str(1000 - j), "sz": "2", "n": 1} for j in range(20)],
                      [{"px": str(1001 + j), "sz": "3", "n": 2} for j in range(20)]]
            encoded = json.dumps({"channel": "l2Book", "data": {"coin": "BTC", "time": event // 10**6, "levels": levels}})
            receipt = datetime.fromtimestamp(event / 10**9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.010Z")
            lines.append(receipt + " " + encoded)
            row = {"source_id": "fictional-btc", "source_ordinal": ordinal, "asset": "BTC", "event_ns": event,
                   "release_ns": None, "admission_evidence_ns": None,
                   "bid_prices_units8": [(1000 - j) * 10**8 for j in range(5)],
                   "ask_prices_units8": [(1001 + j) * 10**8 for j in range(5)],
                   "bid_sizes_units8": [2 * 10**8] * 5, "ask_sizes_units8": [3 * 10**8] * 5,
                   "bid_counts": [1] * 5, "ask_counts": [2] * 5}
            rows.append(row)
            provenance.append({"source_ordinal": ordinal, "chunk_number": 0, "chunk_line_ordinal": ordinal,
                               "provider_receipt_text": receipt, "provider_receipt_ns": event + 10**7,
                               "provider_receipt_role": "uncalibrated provider receipt", "event_ns": event,
                               "disconnect_epoch": int(index >= 100), "raw_bid_depth": 20, "raw_ask_depth": 20,
                               "full_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest()})
        decoded = ("\n".join(lines) + "\n").encode()
        (self.root / "response.gz").write_bytes(gzip.compress(decoded, mtime=0))
        record = {"status": 200, "completed": True, "at_cap": False, "compressed_path": "response.gz",
                  "body_sha256": sha256(self.root / "response.gz"), "received_body_bytes": (self.root / "response.gz").stat().st_size,
                  "decoded_bytes": len(decoded), "decoded_sha256": hashlib.sha256(decoded).hexdigest(),
                  "response_headers": {"Content-Encoding": "gzip"},
                  "url": "https://api.tardis.dev/v1/data-feeds/hyperliquid?from=2025-12-01T00%3A00%3A00.000Z&offset=0&sliceSize=10&filters=%5B%7B%22channel%22%3A%22l2Book%22%2C%22symbols%22%3A%5B%22BTC%22%2C%22ETH%22%5D%7D%5D"}
        self.proof = {"schema": "t008-tardis-acquisition-proof/1", "date": "2025-12-01",
                      "selection_event_start_ns": start, "selection_event_end_ns": start + 600 * 10**9,
                      "records_in_source_order": [{"record": record, "compressed_sha256": record["body_sha256"],
                          "decoded_bytes": len(decoded), "decoded_sha256": record["decoded_sha256"],
                          "gzip_crc_and_decoded_hash_reverified": True}]}
        self.rows, self.provenance = rows, provenance
        self.write_lines("rows.jsonl", rows)
        self.write_lines("source_provenance.jsonl", provenance)
        self.write_json("proof.json", self.proof)
        self.segments = [{"segment_id": n, "first_row_index": a, "stop_row_index": b,
                          "start_ns": rows[a]["event_ns"], "end_ns": rows[b - 1]["event_ns"] + 1,
                          "first_source_ordinal": rows[a]["source_ordinal"], "last_source_ordinal": rows[b - 1]["source_ordinal"]}
                         for n, (a, b) in enumerate(((0, 100), (100, 200)))]
        self.write_json("segments.json", self.segments)
        self.contract = {"schema": "t008-producer-state/2", "version": "2.2.0", "producer": "T-008",
            "purpose": "historical_paired_hyperliquid_sampled_state_adaptation",
            "origin": "synthetic_integration", "fixture_only": True, "asset": "BTC", "date": "2025-12-01",
            "split_roles": {"Q18": "development"}, "policy_file": None, "policy_sha256": None,
            "selected_event_start_ns": start, "selected_event_end_ns": start + 600 * 10**9,
            "units": {"time": "UTC Unix ns", "price": "USD per base asset multiplied by1e8",
                      "size": "base asset multiplied by1e8", "count": "positive visible native order count"},
            "horizons": {"Q18": {"lookback_ns": 75 * 10**9, "label_horizon_ns": 10 * 10**9,
                                    "forward_guard_ns": 10_500_000_000, "guard_kind": "adopted_conservative_padding"}},
            "scopes": {"Q18": {"decision": "affirmative", "clock_scope": "exchange_time",
                                  "state_scope": "top5_at_snapshot_cuts", "continuity_scope": "sampled_snapshots"}},
            "clock_scope": "exchange_time", "atomic_cut": {"kind": "authoritative_snapshot_at_event_time", "evidence": "Fictional test fixture"},
            "review": {"status": "not_issued_by_producer"}, "eligibility_mask": "Retrospective support mask",
            "receipt_semantics": "Uncalibrated provider receipt; release and admission are null",
            "continuity": {"kind": "sampled_snapshots", "max_age_ns": 1_500_000_000, "max_gap_ns": 2 * 10**9,
                           "cadence_ns": 10**9, "all_venue_events_observed": False, "source_segments_file": "segments.json",
                           "source_segments_sha256": sha256(self.root / "segments.json")},
            "acquisition_proof_file": "proof.json", "acquisition_proof_sha256": sha256(self.root / "proof.json"),
            "source_provenance_file": "source_provenance.jsonl", "source_provenance_sha256": sha256(self.root / "source_provenance.jsonl"),
            "sources": [{"source_id": "fictional-btc", "file": "rows.jsonl", "sha256": sha256(self.root / "rows.jsonl"),
                         "provenance": "Fictional bytes only", "rights": "Generated fixture",
                         "acquisition_proof_file": "proof.json", "acquisition_proof_sha256": sha256(self.root / "proof.json")}],
            "windows": [self.window(segment) for segment in self.segments]}
        self.save()

    def write_json(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def write_lines(self, name, values):
        (self.root / name).write_text("".join(json.dumps(row) + "\n" for row in values), encoding="utf-8")

    def window(self, segment):
        return {"window_id": f"fictional-{segment['segment_id']}", "scope": "Q18", "asset": "BTC",
                "segment_id": segment["segment_id"], "start_ns": segment["start_ns"], "end_ns": segment["end_ns"],
                "first_source_ordinal": segment["first_source_ordinal"], "last_source_ordinal": segment["last_source_ordinal"],
                "source_ids": ["fictional-btc"], "evidence_ids": ["fictional-proof", "explicit-segment"], "state_depth": 5,
                "lookback_ns": 75 * 10**9, "forward_guard_ns": 10_500_000_000, "max_age_ns": 1_500_000_000,
                "use": "prespecified_chronological_split"}

    def save(self):
        self.write_json("contract.json", self.contract)

    def read(self):
        policy = STARTUP_POLICY_SHA if self.contract["version"] == "2.3.0" else POLICY_SHA
        return read_paired_contract(self.path, sha256(self.path), policy, allow_development=True)

    def refresh_normalized(self):
        self.write_lines("rows.jsonl", self.rows)
        self.write_lines("source_provenance.jsonl", self.provenance)
        epochs = {item["source_ordinal"]: item["disconnect_epoch"] for item in self.provenance}
        starts = [0] + [i for i in range(1, len(self.rows)) if epochs[self.rows[i]["source_ordinal"]] != epochs[self.rows[i - 1]["source_ordinal"]]]
        self.segments = [{"segment_id": n, "first_row_index": a, "stop_row_index": b,
                          "start_ns": self.rows[a]["event_ns"], "end_ns": self.rows[b - 1]["event_ns"] + 1,
                          "first_source_ordinal": self.rows[a]["source_ordinal"], "last_source_ordinal": self.rows[b - 1]["source_ordinal"]}
                         for n, (a, b) in enumerate(zip(starts, starts[1:] + [len(self.rows)]))]
        self.write_json("segments.json", self.segments)
        self.contract["continuity"]["source_segments_sha256"] = sha256(self.root / "segments.json")
        self.contract["sources"][0]["sha256"] = sha256(self.root / "rows.jsonl")
        self.contract["source_provenance_sha256"] = sha256(self.root / "source_provenance.jsonl")
        self.contract["sources"][0].update(source_provenance_file="source_provenance.jsonl",
                                          source_provenance_sha256=self.contract["source_provenance_sha256"])
        self.contract["windows"] = [self.window(segment) for segment in self.segments if segment["end_ns"] - segment["start_ns"] > 85_500_000_000]
        self.save()

    def refresh_proof(self, decoded=None):
        if decoded is not None:
            (self.root / "response.gz").write_bytes(gzip.compress(decoded, mtime=0))
            item = self.proof["records_in_source_order"][0]
            item["record"].update(body_sha256=sha256(self.root / "response.gz"), received_body_bytes=(self.root / "response.gz").stat().st_size,
                                  decoded_bytes=len(decoded), decoded_sha256=hashlib.sha256(decoded).hexdigest())
            item.update(compressed_sha256=item["record"]["body_sha256"], decoded_bytes=len(decoded), decoded_sha256=item["record"]["decoded_sha256"])
        self.write_json("proof.json", self.proof)
        self.contract["acquisition_proof_sha256"] = sha256(self.root / "proof.json")
        self.contract["sources"][0]["acquisition_proof_sha256"] = self.contract["acquisition_proof_sha256"]
        self.save()

    def startup_fixture(self):
        prefix = [{**{k: item[k] for k in ("source_ordinal", "chunk_number", "chunk_line_ordinal", "provider_receipt_text", "provider_receipt_ns", "event_ns", "full_payload_sha256")},
                   "asset": "BTC", "reason": "fixed_provider_receipt_prefix_before_UTC_00_00_30"} for item in self.provenance[:30]]
        self.write_lines("exclusions.jsonl", prefix)
        self.rows, self.provenance = self.rows[30:], self.provenance[30:]
        (self.root / "normalizer.py").write_text("# Explicit fictional fixture; never executed.\n")
        self.contract.update(version="2.3.0", startup_exclusion_ns=30 * 10**9,
                             adaptation_class="SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT",
                             selection_qualification="Fictional fixture for post-acquisition source-quality selection",
                             restart_claim="No authenticated restart", fit_authorization_gate="No model fits in fixture",
                             source_acquisition_policy_file=None, source_acquisition_policy_sha256=POLICY_SHA,
                             normalizer_source_file="normalizer.py", normalizer_code_sha256=sha256(self.root / "normalizer.py"),
                             receipt_prefix_exclusions_file="exclusions.jsonl", receipt_prefix_exclusions_sha256=sha256(self.root / "exclusions.jsonl"))
        self.contract["selected_event_start_ns"] += 30 * 10**9
        self.proof["selection_event_start_ns"] = self.contract["selected_event_start_ns"]
        self.refresh_proof()
        self.refresh_normalized()

    def test_fictional_opt_in_preserves_bytes_and_two_segments(self):
        before = self.path.read_bytes()
        contract, sources, segments, provenance = self.read()
        rows, audit = read_paired_rows(contract, sources, segments, provenance)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(contract, self.contract)
        self.assertEqual(len(rows), 200)
        self.assertEqual(audit["source_segments"], 2)
        self.assertTrue(provenance["development_only"])
        self.assertEqual(provenance["acquisition_proof"], self.proof)

    def test_development_and_fixtures_require_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "explicit opt-in"):
            read_paired_contract(self.path, sha256(self.path), POLICY_SHA)

    def test_additive_revision_preserves_original_contract(self):
        self.write_json("old_contract.json", self.contract)
        (self.root / "normalizer.py").write_text("# Fictional source, never executed.\n")
        self.contract.update(version="2.2.1", supersedes_contract_file="old_contract.json",
                             supersedes_contract_sha256=sha256(self.root / "old_contract.json"),
                             normalizer_source_file="normalizer.py", normalizer_code_sha256=sha256(self.root / "normalizer.py"))
        self.contract["sources"][0].update(source_provenance_file="source_provenance.jsonl",
                                          source_provenance_sha256=self.contract["source_provenance_sha256"])
        self.save()
        self.assertEqual(self.read()[0]["version"], "2.2.1")
        self.contract["scopes"]["Q18"]["state_scope"] = "altered"
        self.save()
        with self.assertRaisesRegex(ValueError, "changes original producer semantics"):
            self.read()

    def test_negative_and_unrecognized_origins_rejected(self):
        for origin in (None, "eligible_empirical", "unknown", "exploratory_real"):
            with self.subTest(origin=origin):
                self.contract["origin"] = origin
                self.save()
                with self.assertRaisesRegex(ValueError, "origin/fixture"):
                    self.read()

    def test_wrong_expected_hash_and_policy_rejected(self):
        with self.assertRaisesRegex(ValueError, "contract hash"):
            read_paired_contract(self.path, "0" * 64, POLICY_SHA, True)
        with self.assertRaisesRegex(ValueError, "approved policy"):
            read_paired_contract(self.path, sha256(self.path), "0" * 64, True)
        self.contract.update(policy_sha256="0" * 64, policy_file="missing.json")
        self.save()
        with self.assertRaisesRegex(ValueError, "policy hash"):
            self.read()

    def test_payload_proof_segments_provenance_and_compressed_mutation_rejected(self):
        for name in ("rows.jsonl", "proof.json", "segments.json", "source_provenance.jsonl", "response.gz"):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "hash mismatch"):
                self.read()
            path.write_bytes(original)

    def test_decoded_hash_is_recomputed(self):
        item = self.proof["records_in_source_order"][0]
        item["record"]["decoded_sha256"] = item["decoded_sha256"] = "0" * 64
        self.write_json("proof.json", self.proof)
        self.contract["acquisition_proof_sha256"] = sha256(self.root / "proof.json")
        self.contract["sources"][0]["acquisition_proof_sha256"] = self.contract["acquisition_proof_sha256"]
        self.save()
        with self.assertRaisesRegex(ValueError, "Decoded response"):
            self.read()

    def test_window_cannot_cross_short_disconnect(self):
        self.contract["windows"][0].update(end_ns=self.segments[1]["end_ns"], last_source_ordinal=200)
        self.save()
        with self.assertRaisesRegex(ValueError, "crosses explicit source segment"):
            self.read()

    def test_forged_merged_segment_still_rejected_by_disconnect_epoch(self):
        merged = {**self.segments[0], "end_ns": self.segments[1]["end_ns"], "last_source_ordinal": 200, "stop_row_index": 200}
        self.write_json("segments.json", [merged])
        self.contract["continuity"]["source_segments_sha256"] = sha256(self.root / "segments.json")
        self.contract["windows"] = [self.window(merged)]
        self.save()
        with self.assertRaisesRegex(ValueError, "gap or disconnect"):
            read_paired_rows(*self.read())

    def test_fabricated_receipt_or_missing_native_counts_rejected(self):
        for key, value in (("release_ns", 1), ("bid_counts", [None] * 5)):
            original = self.rows[0][key]
            self.rows[0][key] = value
            self.write_lines("rows.jsonl", self.rows)
            self.contract["sources"][0]["sha256"] = sha256(self.root / "rows.jsonl")
            self.save()
            with self.subTest(key=key), self.assertRaises(ValueError):
                read_paired_rows(*self.read())
            self.rows[0][key] = original

    def test_negative_scope_and_weakened_guard_rejected(self):
        self.contract["scopes"]["Q18"]["decision"] = "negative"
        self.save()
        with self.assertRaisesRegex(ValueError, "scope"):
            self.read()
        self.contract["scopes"]["Q18"]["decision"] = "affirmative"
        self.contract["horizons"]["Q18"]["forward_guard_ns"] = 10 * 10**9
        self.save()
        with self.assertRaisesRegex(ValueError, "horizons"):
            self.read()

    def test_source_event_inversion_is_rejected_without_sorting(self):
        self.rows[2]["event_ns"] = self.rows[0]["event_ns"]
        self.write_lines("rows.jsonl", self.rows)
        self.contract["sources"][0]["sha256"] = sha256(self.root / "rows.jsonl")
        self.save()
        with self.assertRaisesRegex(ValueError, "inversion"):
            read_paired_rows(*self.read())

    def test_rehashed_normalized_values_cannot_disagree_with_raw(self):
        self.rows[0]["bid_sizes_units8"][0] += 1
        self.write_lines("rows.jsonl", self.rows)
        self.contract["sources"][0]["sha256"] = sha256(self.root / "rows.jsonl")
        self.save()
        with self.assertRaisesRegex(ValueError, "top-five values differ from raw"):
            read_paired_rows(*self.read())

    def test_rehashed_provenance_cannot_forge_raw_payload_hash(self):
        self.provenance[0]["full_payload_sha256"] = "0" * 64
        self.write_lines("source_provenance.jsonl", self.provenance)
        self.contract["source_provenance_sha256"] = sha256(self.root / "source_provenance.jsonl")
        self.save()
        with self.assertRaisesRegex(ValueError, "Raw message differs"):
            read_paired_rows(*self.read())

    def test_startup_exclusion_is_separate_and_exact(self):
        self.startup_fixture()
        contract, sources, segments, provenance = self.read()
        rows, audit = read_paired_rows(contract, sources, segments, provenance)
        self.assertEqual(len(rows), 170)
        self.assertEqual(audit["receipt_prefix_exclusions_verified"], 30)
        self.assertEqual(audit["retained_raw_messages_order_checked"], 170)
        self.assertEqual(rows[0]["event_ns"], contract["selected_event_start_ns"])
        with self.assertRaisesRegex(ValueError, "approved policy"):
            read_paired_contract(self.path, sha256(self.path), POLICY_SHA, True)

    def test_startup_prefix_state_cannot_reenter_even_with_rehashed_files(self):
        self.startup_fixture()
        lines = gzip.decompress((self.root / "response.gz").read_bytes()).decode().splitlines()
        lines[30] = "2025-12-01T00:00:29.999Z " + lines[30].split(" ", 1)[1]
        self.refresh_proof(("\n".join(lines) + "\n").encode())
        with self.assertRaisesRegex(ValueError, "prefix state reenters"):
            read_paired_rows(*self.read())

    def test_retained_inversion_cannot_hide_before_analytical_event_boundary(self):
        self.startup_fixture()
        lines = gzip.decompress((self.root / "response.gz").read_bytes()).decode().splitlines()
        for ordinal, seconds in ((30, 29), (31, 28)):
            receipt, encoded = lines[ordinal].split(" ", 1)
            payload = json.loads(encoded)
            payload["data"]["time"] = self.contract["selected_event_start_ns"] // 10**6 + (seconds - 30) * 1000
            lines[ordinal] = receipt + " " + json.dumps(payload)
        self.rows, self.provenance = self.rows[2:], self.provenance[2:]
        self.refresh_normalized()
        self.refresh_proof(("\n".join(lines) + "\n").encode())
        with self.assertRaisesRegex(ValueError, "Retained raw event inversion"):
            read_paired_rows(*self.read())

    def test_startup_rehashed_count_tampering_is_rejected(self):
        self.startup_fixture()
        self.rows[0]["bid_counts"][0] += 1
        self.refresh_normalized()
        with self.assertRaisesRegex(ValueError, "native counts differ"):
            read_paired_rows(*self.read())

    def test_startup_exclusion_ledger_is_independently_matched(self):
        self.startup_fixture()
        ledger = [json.loads(line) for line in (self.root / "exclusions.jsonl").read_text().splitlines()]
        ledger[0]["full_payload_sha256"] = "0" * 64
        self.write_lines("exclusions.jsonl", ledger)
        self.contract["receipt_prefix_exclusions_sha256"] = sha256(self.root / "exclusions.jsonl")
        self.save()
        with self.assertRaisesRegex(ValueError, "exclusion ledger differs"):
            read_paired_rows(*self.read())


if __name__ == "__main__":
    unittest.main()
