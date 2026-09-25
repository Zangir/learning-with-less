"""Authored, temporary review receipts test bindings; none is a real RV-011 verdict."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from q17_transfer.gate import sha256
from q17_transfer.panel_review import STARTUP_POLICY_SHA256, require_reviewed_amendment


class ReviewedAmendmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.index_path, self.review_path, self.amendment_path = [root/name for name in ("index.json", "review.md", "amendment.json")]
        self.contracts = [dict(asset=asset, date=f"authored-date-{i}",
            sha256=hashlib.sha256(f"{asset}/{i}".encode()).hexdigest())
            for asset in ("BTC", "ETH") for i in range(12)]
        self.index = dict(policy_sha256=STARTUP_POLICY_SHA256, contracts=[dict(asset=c["asset"],
            date=c["date"], contract_sha256=c["sha256"]) for c in self.contracts])
        self.index_path.write_text(json.dumps(self.index), encoding="utf-8")
        index_hash = sha256(self.index_path)
        self.review_path.write_text(f"Authored fixture only, not an actual review.\nPolicy {STARTUP_POLICY_SHA256}\nIndex {index_hash}\n", encoding="utf-8")
        self.amendment = dict(schema="q17-reviewed-source-amendment/1",
            base_predeclaration_sha256="authored-base-freeze", provider_protocol_sha256=STARTUP_POLICY_SHA256,
            period="hour00", startup_exclusion_ns=30_000_000_000,
            adaptation_class="SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT",
            model_policy_constants_unchanged=True, input_index_file=str(self.index_path),
            input_index_sha256=index_hash, review=dict(review_id="RV-011", reviewer_task="T-013",
                decision="supported_exact_hour00_inputs", scope="limited_descriptive_hour00",
                input_index_sha256=index_hash, provider_protocol_sha256=STARTUP_POLICY_SHA256,
                contract_sha256_set=sorted(c["sha256"] for c in self.contracts),
                file=str(self.review_path), sha256=sha256(self.review_path)))
        self.seal_amendment()

    def seal_amendment(self):
        self.amendment_path.write_text(json.dumps(self.amendment), encoding="utf-8")
        self.binding = dict(path=str(self.amendment_path), sha256=sha256(self.amendment_path))

    def check(self, contracts=None, period="hour00"):
        return require_reviewed_amendment(self.binding, self.contracts if contracts is None else contracts,
                                         period, "authored-base-freeze")

    def test_exact_receipt_binds_all_inputs_and_amendment_hash(self):
        result = self.check()
        self.assertEqual(result["consumer_amendment_sha256"], self.binding["sha256"])
        self.assertEqual(result["review"]["contract_sha256_set"], sorted(c["sha256"] for c in self.contracts))

    def test_outer_amendment_and_index_tampering_are_rejected(self):
        self.amendment_path.write_text(self.amendment_path.read_text()+" ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "amendment checksum"):
            self.check()
        self.seal_amendment()
        self.index_path.write_text(self.index_path.read_text()+" ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "index checksum"):
            self.check()

    def test_review_artifact_tampering_and_rehashed_old_review_are_rejected(self):
        self.review_path.write_text("Authored old review, without the amended input hashes", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "review artifact checksum"):
            self.check()
        self.amendment["review"]["sha256"] = sha256(self.review_path)
        self.seal_amendment()
        with self.assertRaisesRegex(ValueError, "identify exact"):
            self.check()

    def test_fewer_or_changed_contracts_cannot_reuse_review(self):
        with self.assertRaisesRegex(ValueError, "24-contract"):
            self.check(self.contracts[:-1])
        changed = copy.deepcopy(self.contracts)
        changed[0]["sha256"] = "0"*64
        with self.assertRaisesRegex(ValueError, "24-contract"):
            self.check(changed)

    def test_old_plan_only_scope_or_contract_receipts_are_rejected(self):
        original = copy.deepcopy(self.amendment)
        for key, value in (("review_id", "RV-008"), ("reviewer_task", "T-014"),
                           ("decision", "supported_plan_only"), ("scope", "full_day"),
                           ("input_index_sha256", "old-index"), ("provider_protocol_sha256", "old-policy"),
                           ("contract_sha256_set", original["review"]["contract_sha256_set"][:-1])):
            self.amendment = copy.deepcopy(original)
            self.amendment["review"][key] = value
            self.seal_amendment()
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "RV011"):
                self.check()

    def test_changed_base_policy_cutoff_or_design_claim_is_rejected(self):
        original = copy.deepcopy(self.amendment)
        for key, value in (("base_predeclaration_sha256", "old-freeze"),
                           ("provider_protocol_sha256", "old-policy"), ("startup_exclusion_ns", 31_000_000_000),
                           ("adaptation_class", "PRE-ACQUISITION"), ("model_policy_constants_unchanged", False)):
            self.amendment = copy.deepcopy(original)
            self.amendment[key] = value
            self.seal_amendment()
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "authorized separate hour00"):
                self.check()

    def test_hour_review_never_authorizes_full_day(self):
        with self.assertRaisesRegex(ValueError, "authorized separate hour00"):
            self.check(period="full_day")
        self.amendment["period"] = "full_day"
        self.seal_amendment()
        with self.assertRaisesRegex(ValueError, "authorized separate hour00"):
            self.check(period="full_day")


if __name__ == "__main__":
    unittest.main()
