"""Mocked runner admission guards; no archive mirrors, estimators or real fits."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from q17_transfer import panel_runner
from q17_transfer.panel_review import STARTUP_POLICY_SHA256
from q17_transfer.protocol import PROTOCOL, digest_json


def plan_fixture():
    return dict(roles=dict(panel_runner.ROLES), provider_protocol_sha256=panel_runner.PROVIDER_PROTOCOL_SHA256,
                source_protocol=copy.deepcopy(PROTOCOL), source_protocol_sha256=digest_json(PROTOCOL))


def binding_fixture():
    return [dict(asset=asset, date=date, path=f"authored/{asset}/{date}", sha256="authored-digest")
            for asset in ("BTC", "ETH") for date in panel_runner.ROLES]


def loaded_fixture(path, expected_sha256):
    _, asset, date = path.split("/")
    start = int(np.datetime64(date, "ns").astype(np.int64))
    return dict(contract=dict(asset=asset, date=date, split_roles={"Q17": panel_runner.ROLES[date]},
                policy_sha256=panel_runner.PROVIDER_PROTOCOL_SHA256,
                selected_event_start_ns=start, selected_event_end_ns=start+3600_000_000_000),
                acquisition_verification={"authored_mock": True})


class PanelRunnerGuardTests(unittest.TestCase):
    def invoke(self, plan=None, bindings=None, loader=loaded_fixture, expected_error=None,
               projector=None, reviewed_amendment=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            predeclaration = root/"authored_plan.json"
            predeclaration.write_text(json.dumps(plan_fixture() if plan is None else plan), encoding="utf-8")
            with patch.object(panel_runner, "PREDECLARATION_SHA256", panel_runner.sha256(predeclaration)), \
                    patch.object(panel_runner, "require_fit_runtime"), \
                    patch("q17_transfer.panel_contract.load_panel_contract", side_effect=loader) as load, \
                    patch.object(panel_runner, "project_day", side_effect=projector or ValueError("Unavailable authored fixture")) as project, \
                    patch.object(panel_runner, "fit_evaluate") as fit:
                if expected_error:
                    with self.assertRaisesRegex(ValueError, expected_error):
                        panel_runner.run_panel(binding_fixture() if bindings is None else bindings,
                                               predeclaration, root/"output", "hour00", reviewed_amendment=reviewed_amendment)
                    result = None
                else:
                    result = panel_runner.run_panel(binding_fixture(), predeclaration, root/"output", "hour00",
                                                    reviewed_amendment=reviewed_amendment)
                fit.assert_not_called()
                return result, load.call_count, project.call_count

    def test_frozen_source_object_and_digest_are_checked_before_loading(self):
        for field in ("source_protocol", "source_protocol_sha256"):
            plan = plan_fixture()
            if field == "source_protocol":
                plan[field]["horizon_seconds"] = 20
            else:
                plan[field] = "authored-stale-digest"
            with self.subTest(field=field):
                _, loads, projections = self.invoke(plan=plan, expected_error="constants changed")
                self.assertEqual((loads, projections), (0, 0))

    def test_changed_runtime_constant_cannot_use_unchanged_frozen_plan(self):
        frozen = plan_fixture()
        with patch.dict(PROTOCOL, training_cap_per_day=5999):
            _, loads, _ = self.invoke(plan=frozen, expected_error="constants changed")
        self.assertEqual(loads, 0)

    def test_missing_or_duplicate_bindings_fail_before_loading(self):
        bindings = binding_fixture()
        for sample in (bindings[:-1], bindings[:-1]+[bindings[0]]):
            with self.subTest(keys=len({(b['asset'], b['date']) for b in sample})):
                _, loads, _ = self.invoke(bindings=sample, expected_error="fixed 24")
                self.assertEqual(loads, 0)

    def test_loaded_asset_date_role_and_provider_policy_must_match(self):
        for field, value in (("asset", "ETH"), ("date", "2025-02-01"),
                             ("split_roles", {"Q17": "validation"}), ("policy_sha256", "stale")):
            def changed(path, expected_sha256):
                loaded = loaded_fixture(path, expected_sha256)
                loaded["contract"][field] = value
                return loaded
            with self.subTest(field=field):
                _, loads, projections = self.invoke(loader=changed, expected_error="Contract differs")
                self.assertEqual((loads, projections), (1, 0))

    def test_selected_period_must_match_exact_event_bounds(self):
        for field in ("selected_event_start_ns", "selected_event_end_ns"):
            def shifted(path, expected_sha256):
                loaded = loaded_fixture(path, expected_sha256)
                loaded["contract"][field] += 1
                return loaded
            with self.subTest(field=field):
                _, loads, projections = self.invoke(loader=shifted, expected_error="declared period")
                self.assertEqual((loads, projections), (1, 0))

    def test_unavailable_projection_never_fits_or_manufactures_gate_failure(self):
        result, loads, projections = self.invoke()
        self.assertEqual((loads, projections), (24, 24))
        self.assertEqual(result["status"], "not_evaluable")
        self.assertIsNone(result["adapted_joint_rule_passed"])
        self.assertEqual(result["actual_model_fits"], 0)
        self.assertEqual(result["contrasts"], [])
        self.assertEqual(result["original_source_primary"], "failed and not re-evaluated")

    @staticmethod
    def amended_loader(path, expected_sha256):
        loaded = loaded_fixture(path, expected_sha256)
        loaded["contract"]["policy_sha256"] = STARTUP_POLICY_SHA256
        loaded["contract"]["selected_event_start_ns"] += 30_000_000_000
        return loaded

    @staticmethod
    def amended_projection(loaded, asset, date, split, period):
        start = int(np.datetime64(date, "ns").astype(np.int64))
        times = start+51_000_000_000+np.arange(12, dtype=np.int64)*11_000_000_000
        return dict(times=times, y=np.tile([0, 1, 2], 4),
                    outcome_available_ns=times+11_000_000_000,
                    schedule_rows=np.arange(12).reshape(1, 12)), {"authored_mock": True}

    def test_amended_contract_without_review_fails_before_projection(self):
        _, loads, projections = self.invoke(loader=self.amended_loader, expected_error="Contract differs")
        self.assertEqual((loads, projections), (1, 0))

    def test_rejected_rv011_amendment_stops_before_any_contract_load(self):
        with patch("q17_transfer.panel_review.require_reviewed_amendment", side_effect=ValueError("RV011 not supported")):
            _, loads, projections = self.invoke(reviewed_amendment={"authored_mock": True}, expected_error="RV011")
        self.assertEqual((loads, projections), (0, 0))

    def test_amended_panel_preflights_every_asset_before_any_fit(self):
        authorization = dict(provider_protocol_sha256=STARTUP_POLICY_SHA256,
                             startup_exclusion_ns=30_000_000_000, authored_mock=True)
        for failure in ("missing_test_support", "second_asset_training_class", "second_asset_outcome_maturity"):
            def projected(loaded, asset, date, split, period):
                if failure == "missing_test_support" and asset == "ETH" and date == "2025-11-01":
                    raise ValueError("Unavailable authored missing test support")
                day, diagnostic = self.amended_projection(loaded, asset, date, split, period)
                if asset == "ETH" and split == "train":
                    if failure == "second_asset_training_class":
                        day["y"][:] = 1
                    elif failure == "second_asset_outcome_maturity":
                        day["outcome_available_ns"][:] = int(np.datetime64("2025-04-02", "ns").astype(np.int64))
                return day, diagnostic
            with self.subTest(failure=failure), patch("q17_transfer.panel_review.require_reviewed_amendment", return_value=authorization):
                result, loads, projections = self.invoke(loader=self.amended_loader, projector=projected,
                                                         reviewed_amendment={"authored_mock": True})
                self.assertEqual((loads, projections), (24, 24))
                self.assertEqual(result["actual_model_fits"], 0)
                self.assertEqual(result["status"], "not_evaluable")
                self.assertIsNone(result["adapted_joint_rule_passed"])
                self.assertTrue(result["unavailable"])


if __name__ == "__main__":
    unittest.main()
