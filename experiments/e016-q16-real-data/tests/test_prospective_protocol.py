"""RV033 B2: hash binding must not authorize a different scientific design."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from admission import sha256
from prospective import EXECUTABLE_PROTOCOL, SourceBlocked, load_bundle, validate_protocol


class FrozenProtocolTests(unittest.TestCase):
    def test_every_frozen_field_rejects_changed_or_missing_value(self):
        protocol = deepcopy(EXECUTABLE_PROTOCOL)
        protocol["scope"] = {"software_fixture_only": "RV033-B2"}
        validate_protocol(protocol)
        for key in protocol.keys() - {"scope"}:
            for alteration in ("changed", "missing"):
                with self.subTest(field=key, alteration=alteration):
                    changed = deepcopy(protocol)
                    if alteration == "missing":
                        del changed[key]
                    else:
                        changed[key] = {"unsupported_value": True}
                    with self.assertRaises(SourceBlocked):
                        validate_protocol(changed)
        with self.assertRaises(SourceBlocked):
            validate_protocol({**protocol, "cost_override": 99})
        with self.assertRaises(SourceBlocked):
            validate_protocol({**protocol, "scope": None})
        with self.assertRaises(SourceBlocked):
            validate_protocol({**protocol, "horizon": 8.0})

    def test_rehashed_changed_costs_arms_selection_and_endpoints_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p, c = root / "protocol.json", root / "contract.json"
            for changes in ({"fallback_costs": [2, 4], "incomplete_execution_cost": 99},
                            {"incomplete_execution_cost": 99},
                            {"observer_arms": ["volume", "other"]},
                            {"selection": "select_only_eventually_filled"},
                            {"primary_endpoint": "realized_profit"},
                            {"secondary_endpoint": "another_endpoint"}):
                with self.subTest(changes=changes):
                    protocol = {**deepcopy(EXECUTABLE_PROTOCOL),
                                "scope": {"software_fixture_only": "RV033-B2"}, **changes}
                    p.write_text(json.dumps(protocol))
                    c.write_text(json.dumps({"schema": "q16-offline-source/1", "producer": "T-018",
                                             "origin": "real_native", "fixture_only": False,
                                             "protocol_sha256": sha256(p)}))
                    with self.assertRaisesRegex(SourceBlocked, "Unsupported frozen protocol field"):
                        load_bundle(c, p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
