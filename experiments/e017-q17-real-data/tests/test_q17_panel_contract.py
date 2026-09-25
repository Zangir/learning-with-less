"""Authored archive-chain mechanics; these fixtures are not market evidence."""
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from q17_transfer import panel_contract as panel
from q17_transfer.gate import sha256


class PanelContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.date = "2025-01-01"
        self.start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()) * panel.NS
        policy = {"roles_Q17": {self.date: "train"}, "roles_Q18": {self.date: "train"}}
        self.write("policy.json", policy)
        self.policy_hash = sha256(self.root / "policy.json")
        mocked_policy = patch.object(panel, "POLICY_SHA256", self.policy_hash)
        mocked_policy.start()
        self.addCleanup(mocked_policy.stop)
        self.write("preflight.json", {"protocol_sha256": self.policy_hash})
        self.write("authorization.json", {"protocol_sha256": self.policy_hash})
        self.payloads = []
        self.expected_rows = []
        ordinal = 0
        # Short source segments and one sub-second disconnect exercise boundaries
        # independently from the required ten-minute acquisition partitioning.
        self.segments = []
        for chunk in range(6):
            texts = []
            first = len(self.expected_rows)
            for second in (0, 1):
                event = self.start + (chunk * 600 + second) * panel.NS
                payload = self.envelope(event)
                receipt = datetime.fromtimestamp(event / panel.NS, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".1234567Z"
                texts.append(receipt + " " + json.dumps(payload, separators=(",", ":")) + "\n")
                row = {"source_id": f"tardis-hyperliquid-{self.date}-btc", "source_ordinal": ordinal,
                       "asset": "BTC", "event_ns": event, "release_ns": None, "admission_evidence_ns": None}
                for side, levels in zip(("bid", "ask"), payload["data"]["levels"]):
                    row[side + "_prices_units8"] = [int(x["px"]) * 100_000_000 for x in levels[:5]]
                    row[side + "_sizes_units8"] = [100_000_000] * 5
                    row[side + "_counts"] = [2] * 5
                self.expected_rows.append(row)
                ordinal += 1
            self.payloads.append("".join(texts).encode())
            self.segments.append({"segment_id": chunk, "first_row_index": first, "stop_row_index": first + 2,
                "start_ns": self.expected_rows[first]["event_ns"], "end_ns": self.expected_rows[first + 1]["event_ns"] + 1,
                "first_source_ordinal": first, "last_source_ordinal": first + 1})
        self.source = {"source_id": f"tardis-hyperliquid-{self.date}-btc", "file": "rows.jsonl",
                       "acquisition_proof_file": "proof.json"}
        self.contract = {
            "schema": "t008-producer-state/2", "version": "2.2.0", "producer": "T-008",
            "origin": "exploratory_real", "fixture_only": False,
            "purpose": "historical_paired_hyperliquid_sampled_state_adaptation",
            "asset": "BTC", "date": self.date, "split_roles": {"Q17": "train", "Q18": "train"},
            "sources": [self.source], "units": {"time": "UTC Unix ns", "price": "USD per base asset multiplied by1e8",
                "size": "base asset multiplied by1e8", "count": "positive visible native order count"},
            "review": {"status": "not_issued_by_producer"}, "clock_scope": "exchange_time",
            "source_authenticity": "third_party_not_independently_authenticated",
            "scopes": {"Q17": {"decision": "affirmative", "clock_scope": "exchange_time",
                "state_scope": "bbo_at_snapshot_cuts", "continuity_scope": "sampled_snapshots"}},
            "atomic_cut": {"kind": "authoritative_snapshot_at_event_time", "authority_scope": "claimed_by_third_party_archive_only", "evidence": "authored fixture"},
            "continuity": {"kind": "sampled_snapshots", "all_venue_events_observed": False,
                "max_age_ns": 1_500_000_000, "max_gap_ns": 2_000_000_000, "source_segments_file": "segments.json"},
            "horizons": {name: {"lookback_ns": 20 * panel.NS, "forward_guard_ns": forward} for name, forward in (
                ("Q17_forecast", 10 * panel.NS), ("Q17_primary_utility", 10_100_000_000),
                ("Q17_full_latency_grid", 10_500_000_000), ("Q17_scheduling", 131_500_000_000))},
            "policy_file": str(self.root / "policy.json"), "policy_sha256": self.policy_hash,
            "selected_event_start_ns": self.start, "selected_event_end_ns": self.start + 3600 * panel.NS,
            "actual_first_event_ns": self.expected_rows[0]["event_ns"], "actual_last_event_ns": self.expected_rows[-1]["event_ns"],
            "acquisition_proof_file": "proof.json", "windows": []}
        self.contract["horizons"]["Q17_scheduling"].update(opportunities=12, grid_ns=11 * panel.NS)
        for segment in self.segments:
            self.contract["windows"].append({key: value for key, value in segment.items()
                if key not in {"first_row_index", "stop_row_index"}} | {"window_id": str(segment["segment_id"]),
                "scope": "Q17", "asset": "BTC", "source_ids": [self.source["source_id"]], "state_depth": 1,
                "use": "prespecified_chronological_split", "max_age_ns": 1_500_000_000,
                "lookback_ns": 20 * panel.NS, "forward_guard_ns": 10_500_000_000})
        self.rebind()

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def envelope(self, event):
        return {"channel": "l2Book", "data": {"time": event // 1_000_000, "coin": "BTC",
            "levels": [[{"px": str(100 - i), "sz": "1", "n": 2} for i in range(20)],
                       [{"px": str(101 + i), "sz": "1", "n": 2} for i in range(20)]]}}

    def rebind(self):
        self.proof = {"schema": "t008-tardis-acquisition-proof/1", "date": self.date,
            "selection_event_start_ns": self.start, "selection_event_end_ns": self.start + 3600 * panel.NS,
            "records_in_source_order": []}
        for chunk, decoded in enumerate(self.payloads):
            compressed_path = self.root / f"chunk{chunk}.gz"
            compressed_path.write_bytes(gzip.compress(decoded, mtime=0))
            record = {"date": self.date, "role": "train", "offset": chunk * 10,
                "protocol_sha256": self.policy_hash, "protocol_path": str(self.root / "policy.json"),
                "url": "https://api.tardis.dev/v1/data-feeds/hyperliquid?" + urlencode({
                    "from": self.date + "T00:00:00.000Z", "offset": chunk * 10, "sliceSize": 10,
                    "filters": json.dumps([{"channel": "l2Book", "symbols": ["BTC", "ETH"]}]), "compression": "gzip"}),
                "compressed_path": str(compressed_path), "compressed_bytes": compressed_path.stat().st_size,
                "compressed_sha256": sha256(compressed_path), "decoded_bytes": len(decoded),
                "decoded_sha256": hashlib.sha256(decoded).hexdigest(), "source_lines": len(decoded.splitlines()),
                "received_body_bytes": compressed_path.stat().st_size, "status": 200, "completed": True,
                "response_headers": {"Content-Encoding": "gzip", "Content-Length": str(compressed_path.stat().st_size), "x-slice-size": "10"}}
            for stem in ("preflight", "authorization"):
                record[stem + "_path"] = str(self.root / (stem + ".json"))
                record[stem + "_sha256"] = sha256(self.root / (stem + ".json"))
            self.proof["records_in_source_order"].append({"record": record,
                **{key: record[key] for key in ("compressed_sha256", "decoded_sha256", "decoded_bytes")},
                "gzip_crc_and_decoded_hash_reverified": True})
        self.save_rows()
        self.save_proof()
        self.save_segments()
        self.save_contract()

    def save_rows(self):
        path = self.root / "rows.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in self.expected_rows), encoding="utf-8")
        self.source["sha256"] = sha256(path)

    def save_proof(self):
        path = self.write("proof.json", self.proof)
        self.source["acquisition_proof_sha256"] = self.contract["acquisition_proof_sha256"] = sha256(path)

    def save_segments(self):
        self.contract["continuity"]["source_segments_sha256"] = sha256(self.write("segments.json", self.segments))

    def save_contract(self):
        return self.write("contract.json", self.contract)

    def load(self):
        path = self.save_contract()
        return panel.load_panel_contract(path, expected_sha256=sha256(path))

    def upgrade(self):
        old = self.write("previous.json", self.contract)
        self.contract = copy.deepcopy(self.contract)
        self.source = self.contract["sources"][0]
        provenance = []
        ordinal = 0
        for chunk, decoded in enumerate(self.payloads):
            for local, line in enumerate(decoded.decode().splitlines()):
                receipt, encoded = line.split(" ", 1)
                envelope = json.loads(encoded)
                provenance.append({"source_ordinal": ordinal, "chunk_number": chunk, "chunk_line_ordinal": local,
                    "event_ns": envelope["data"]["time"] * 1_000_000, "provider_receipt_text": receipt,
                    "provider_receipt_ns": self.expected_rows[ordinal]["event_ns"] + 123456700,
                    "provider_receipt_role": "provider archive collection timestamp, uncalibrated; not release/admission",
                    "disconnect_epoch": 0, "raw_bid_depth": 20, "raw_ask_depth": 20,
                    "full_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest()})
                ordinal += 1
        path = self.root / "provenance.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in provenance))
        self.contract.update(version="2.2.1", supersedes_contract_file=old.name,
            supersedes_contract_sha256=sha256(old), source_provenance_file=path.name, source_provenance_sha256=sha256(path))
        self.source.update(source_provenance_file=path.name, source_provenance_sha256=sha256(path))
        self.contract["evidence_files"] = {}
        for name in ("eligibility_diagnostics.json", "clock_diagnostics.json", "grid_audit.csv",
                     "q17_required_cut_audit.csv", "q18_endpoint_audit.csv", "duplicate_ledger.json"):
            self.contract["evidence_files"][name] = sha256(self.write(name, {}))
        return provenance

    def test_production_policy_is_pinned_to_authorized_calendar(self):
        self.assertEqual(panel.MAPPING["protocol_sha256"], "84639e7bee796452cae075f4f349e61e8ff37ac4fd9d32685ba0f111baf3120d")

    def test_valid_chain_recovers_exact_rows_segments_and_separate_receipt(self):
        loaded = self.load()
        self.assertEqual(loaded["segments"], self.segments)
        self.assertEqual(loaded["rows"][0]["provider_receive_ns"], self.start + 123456700)
        self.assertIsNone(loaded["rows"][0]["release_ns"])
        self.assertIsNone(loaded["rows"][0]["admission_evidence_ns"])
        self.assertEqual(loaded["acquisition_verification"]["normalized_rows_reconstructed"], 12)
        self.assertFalse(loaded["acquisition_verification"]["empirical_admission"])

    def test_external_contract_and_frozen_policy_hashes_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            panel.load_panel_contract(self.save_contract(), expected_sha256="0" * 64)
        self.contract["policy_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "frozen panel protocol"):
            self.load()

    def test_changed_role_or_period_cannot_be_rebound(self):
        self.contract["split_roles"]["Q17"] = "test"
        with self.assertRaisesRegex(ValueError, "role"):
            self.load()
        self.contract["split_roles"]["Q17"] = "train"
        self.contract["selected_event_end_ns"] -= panel.NS
        with self.assertRaisesRegex(ValueError, "period"):
            self.load()

    def test_admission_and_authority_promotion_rejected(self):
        for field, value in (("source_authenticity", "official"), ("clock_scope", "observed_receive_time")):
            original = self.contract[field]
            self.contract[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "promoted"):
                self.load()
            self.contract[field] = original
        self.expected_rows[0]["release_ns"] = self.start
        self.save_rows()
        with self.assertRaisesRegex(ValueError, "release/admission"):
            self.load()

    def test_normalized_hash_tamper_and_rehashed_projection_tamper_rejected(self):
        with (self.root / "rows.jsonl").open("a") as stream:
            stream.write(" ")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.load()
        self.expected_rows[0]["bid_sizes_units8"][0] += 1
        self.save_rows()
        with self.assertRaisesRegex(ValueError, "exactly reproduce"):
            self.load()

    def test_compressed_tamper_and_rehashed_decoded_digest_tamper_rejected(self):
        (self.root / "chunk0.gz").write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "Compressed response"):
            self.load()
        self.rebind()
        item = self.proof["records_in_source_order"][0]
        item["decoded_sha256"] = item["record"]["decoded_sha256"] = "0" * 64
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "Independently decoded"):
            self.load()

    def test_missing_reordered_slices_or_forged_request_rejected(self):
        self.proof["records_in_source_order"].reverse()
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "ordered period"):
            self.load()
        self.proof["records_in_source_order"].reverse()
        self.proof["records_in_source_order"][0]["record"]["url"] += "&offset=10"
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "endpoint/date/filter/offset"):
            self.load()

    def test_rehashed_segments_or_windows_cannot_bridge_source_gaps(self):
        self.segments[0]["stop_row_index"] += 1
        self.save_segments()
        with self.assertRaisesRegex(ValueError, "disconnect/gap"):
            self.load()
        self.segments[0]["stop_row_index"] -= 1
        self.save_segments()
        self.contract["windows"][0]["end_ns"] += panel.NS
        with self.assertRaisesRegex(ValueError, "window exceeds"):
            self.load()

    def test_full_depth_conflicting_tie_is_not_hidden_by_top_five_projection(self):
        lines = self.payloads[0].decode().splitlines(keepends=True)
        receipt, encoded = lines[0].split(" ", 1)
        envelope = json.loads(encoded)
        envelope["data"]["levels"][0][19]["sz"] = "2"
        lines.insert(1, receipt + " " + json.dumps(envelope) + "\n")
        self.payloads[0] = "".join(lines).encode()
        self.rebind()
        with self.assertRaisesRegex(ValueError, "conflicting full-payload"):
            self.load()

    def test_disconnect_requires_break_even_when_event_gap_is_short(self):
        lines = self.payloads[0].decode().splitlines(keepends=True)
        self.payloads[0] = (lines[0] + "\n" + lines[1]).encode()
        for row in self.expected_rows[1:]:
            row["source_ordinal"] += 1
        self.rebind()
        with self.assertRaisesRegex(ValueError, "disconnect/gap"):
            self.load()

    def test_additive_provenance_patch_preserves_preceding_contract(self):
        self.upgrade()
        self.assertEqual(self.load()["contract"]["version"], "2.2.1")
        self.contract["receipt_semantics"] = "additional scientific reinterpretation"
        with self.assertRaisesRegex(ValueError, "changes previously frozen"):
            self.load()

    def test_bound_receipt_and_clock_audit_tampering_rejected(self):
        provenance = self.upgrade()
        path = self.root / "provenance.jsonl"
        path.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "receipt provenance checksum"):
            self.load()
        provenance[0]["provider_receipt_ns"] += 1
        path.write_text("".join(json.dumps(row) + "\n" for row in provenance))
        self.source["source_provenance_sha256"] = self.contract["source_provenance_sha256"] = sha256(path)
        with self.assertRaisesRegex(ValueError, "does not reproduce raw"):
            self.load()
        (self.root / "clock_diagnostics.json").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "audit checksum"):
            self.load()

    def test_provider_receipt_partition_is_not_interchangeable_with_event_period(self):
        self.payloads[0] = self.payloads[0].replace(b"T00:00:00.1234567Z", b"T00:10:00.1234567Z")
        self.rebind()
        with self.assertRaisesRegex(ValueError, "slice partition"):
            self.load()

    def test_provider_receipt_inversion_rejected_with_increasing_event_times(self):
        self.payloads[0] = self.payloads[0].replace(b"T00:00:01.1234567Z", b"T00:00:00.0000001Z")
        self.rebind()
        with self.assertRaisesRegex(ValueError, "Provider receipt inversion"):
            self.load()

    def startup_case(self):
        self.upgrade()
        prefix = self.payloads[0].decode().splitlines(keepends=True)
        retained = []
        for index, line in enumerate(prefix):
            receipt, encoded = line.split(" ", 1)
            envelope = json.loads(encoded)
            envelope["data"]["time"] = (self.start + (5 - index) * panel.NS) // 1_000_000
            prefix[index] = receipt + " " + json.dumps(envelope) + "\n"
            envelope["data"]["time"] = (self.start + (30 + index) * panel.NS) // 1_000_000
            receipt = f"2025-01-01T00:00:{30 + index:02d}.1234567Z"
            retained.append(receipt + " " + json.dumps(envelope) + "\n")
        self.payloads[0] = "".join(prefix + retained).encode()
        for index, row in enumerate(self.expected_rows):
            row["source_ordinal"] += 2
            if index < 2:
                row["event_ns"] += 30 * panel.NS
        for segment, window in zip(self.segments, self.contract["windows"]):
            for value in (segment, window):
                value["first_source_ordinal"] += 2
                value["last_source_ordinal"] += 2
                if value["segment_id"] == 0:
                    value["start_ns"] += 30 * panel.NS
                    value["end_ns"] += 30 * panel.NS
        self.rebind()
        policy = json.loads((self.root / "policy.json").read_text())
        policy.update(supersedes_policy_sha256=self.policy_hash, startup_exclusion_ns=30 * panel.NS,
            selection_qualification="SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT",
            restart_claim="No authenticated restart inferred", fit_authorization_gate="Exact input review required")
        policy_path = self.write("startup_policy.json", policy)
        patched = patch.object(panel, "STARTUP_POLICY_SHA256", sha256(policy_path))
        patched.start()
        self.addCleanup(patched.stop)
        self.contract.update(version="2.3.0", policy_file=str(policy_path), policy_sha256=sha256(policy_path),
            selected_event_start_ns=self.start + 30 * panel.NS,
            actual_first_event_ns=self.expected_rows[0]["event_ns"],
            source_acquisition_policy_file=str(self.root / "policy.json"), source_acquisition_policy_sha256=self.policy_hash,
            startup_exclusion_ns=30 * panel.NS, adaptation_class=panel.STARTUP_MAPPING["adaptation_class"],
            **{key: policy[key] for key in ("selection_qualification", "restart_claim", "fit_authorization_gate")})
        self.proof["selection_event_start_ns"] = self.contract["selected_event_start_ns"]
        self.save_proof()
        self.write("executed_normalizer.py", {"authored": True})
        self.contract.update(normalizer_source_file="executed_normalizer.py", normalizer_code_sha256=sha256(self.root / "executed_normalizer.py"))
        self.refresh_startup_sidecars()

    def refresh_startup_sidecars(self):
        provenance, exclusions = [], []
        ordinal = 0
        for chunk, decoded in enumerate(self.payloads):
            for local, line in enumerate(decoded.decode().splitlines()):
                receipt, encoded = line.split(" ", 1)
                data = json.loads(encoded)["data"]
                whole, fraction = receipt[:-1].split(".")
                receipt_ns = int(datetime.fromisoformat(whole).replace(tzinfo=timezone.utc).timestamp()) * panel.NS + int(fraction.ljust(9, "0"))
                row = {"source_ordinal": ordinal, "chunk_number": chunk, "chunk_line_ordinal": local,
                    "provider_receipt_text": receipt, "provider_receipt_ns": receipt_ns,
                    "event_ns": data["time"] * 1_000_000, "full_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest()}
                if receipt_ns < self.start + 30 * panel.NS:
                    exclusions.append(row | {"asset": data["coin"], "reason": "fixed_provider_receipt_prefix_before_UTC_00_00_30"})
                else:
                    provenance.append(row | {"provider_receipt_role": "provider archive collection timestamp, uncalibrated; not release/admission",
                        "disconnect_epoch": 0, "raw_bid_depth": 20, "raw_ask_depth": 20})
                ordinal += 1
        for name, rows in (("provenance.jsonl", provenance), ("prefix.jsonl", exclusions)):
            (self.root / name).write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.contract["source_provenance_sha256"] = self.source["source_provenance_sha256"] = sha256(self.root / "provenance.jsonl")
        self.contract.update(receipt_prefix_exclusions_file="prefix.jsonl", receipt_prefix_exclusions_sha256=sha256(self.root / "prefix.jsonl"))

    def test_startup_variant_excludes_receipt_prefix_without_carrying_its_state(self):
        self.startup_case()
        loaded = self.load()
        self.assertEqual(loaded["rows"][0]["event_ns"], self.start + 30 * panel.NS)
        self.assertEqual(loaded["rows"][0]["source_ordinal"], 2)
        self.assertEqual(loaded["acquisition_verification"]["startup_receipt_prefix_excluded"], 2)
        self.assertEqual(loaded["acquisition_verification"]["adaptation_class"], panel.STARTUP_MAPPING["adaptation_class"])
        self.contract["version"] = "2.2.1"
        with self.assertRaisesRegex(ValueError, "frozen panel protocol"):
            self.load()

    def test_startup_remaining_inversion_is_rejected_before_event_filter(self):
        self.startup_case()
        lines = self.payloads[0].decode().splitlines(keepends=True)
        for local, second in ((2, 29), (3, 28)):
            receipt, encoded = lines[local].split(" ", 1)
            envelope = json.loads(encoded)
            envelope["data"]["time"] = (self.start + second * panel.NS) // 1_000_000
            lines[local] = receipt + " " + json.dumps(envelope) + "\n"
        self.payloads[0] = "".join(lines).encode()
        self.rebind()
        self.proof["selection_event_start_ns"] = self.start + 30 * panel.NS
        self.save_proof()
        self.refresh_startup_sidecars()
        with self.assertRaisesRegex(ValueError, "Raw source inversion"):
            self.load()

    def test_startup_cutoff_and_post_acquisition_qualification_cannot_change(self):
        self.startup_case()
        self.contract["startup_exclusion_ns"] = 45 * panel.NS
        with self.assertRaisesRegex(ValueError, "fixed cutoff"):
            self.load()
        self.contract["startup_exclusion_ns"] = 30 * panel.NS
        self.contract["selection_qualification"] = "fully untouched pre-acquisition"
        with self.assertRaisesRegex(ValueError, "qualification"):
            self.load()

    def test_startup_exclusion_ledger_cannot_be_rehashed_to_hide_rows(self):
        self.startup_case()
        (self.root / "prefix.jsonl").write_text("")
        self.contract["receipt_prefix_exclusions_sha256"] = sha256(self.root / "prefix.jsonl")
        with self.assertRaisesRegex(ValueError, "prefix exclusions"):
            self.load()


if __name__ == "__main__":
    unittest.main()
