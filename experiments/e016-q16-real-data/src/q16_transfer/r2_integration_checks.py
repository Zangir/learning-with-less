"""Exercise real producer bytes with origin-specific outputs and negative gates."""
import copy
import json
from pathlib import Path
import tempfile

from admission import sha256
from r2_consumer import ScopeBlocked, load_q16_bundle, run_bundle
from r2_fixture_proposal import payload

ROOT = (Path(__file__).resolve().parents[2] / 'runtime')


def run():
    results = []
    def rejected(label, callback):
        try:
            callback()
        except (ValueError, ScopeBlocked) as exc:
            results.append({"check": label, "passed": True, "reason": str(exc)})
        else:
            raise AssertionError(label)
    negative = ROOT / "inputs/T008-final-v1.0.0.json"
    if sha256(negative) != "c4de49bd28c72195bba0c81ca308e8c9aff9af8807b066c20d77beb2af91935c":
        raise ValueError("Wrong final negative bytes")
    rejected("exact_final_negative_semantically_rejected", lambda: load_q16_bundle(negative))
    fixtures = ROOT / "inputs/producer-fixtures"
    rejected("Q17_Q18_snapshot_not_Q16", lambda: load_q16_bundle(fixtures / "affirmative_shared_contract.json"))
    positive = run_bundle(fixtures / "q16_synthetic_contract.json")
    assert positive["synthetic_episodes_scored"] == 1
    assert positive["eligible_empirical_episodes_scored"] == 0
    assert positive["results"][0]["truth"]["fill_fraction"] == "2/3"
    results.append({"check": "producer_authored_Q16_positive_fixture", "passed": True})
    (ROOT / "producer_positive_result.json").write_text(json.dumps(positive, indent=2) + "\n")
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        data = payload()
        data["origin"] = "eligible_empirical"
        payload_path, contract_path, review_path = [temp / name for name in ("payload.json", "contract.json", "review.json")]
        contract = {"schema": "t008-producer-state/2", "producer": "T-008", "origin": "eligible_empirical",
                    "fixture_only": False, "scopes": {"Q16": {"decision": "affirmative"}},
                    "q16_payload": {"file": "payload.json"}}
        def save(candidate, synthetic_review=False):
            payload_path.write_text(json.dumps(candidate))
            contract["q16_payload"]["sha256"] = sha256(payload_path)
            contract_path.write_text(json.dumps(contract))
            review_path.write_text(json.dumps({"role": "coordinator", "decision": "approved", "scope": "Q16",
                "contract_sha256": sha256(contract_path), "evidence": "isolated negative-test fixture",
                "origin": "synthetic_integration" if synthetic_review else "eligible_empirical",
                "fixture_only": synthetic_review}))
        save(data, synthetic_review=True)
        rejected("synthetic_review_cannot_approve_empirical_origin", lambda: load_q16_bundle(contract_path, review_path))
        altered = copy.deepcopy(data)
        altered["episodes"][0]["start_ns"] = -1
        save(altered)
        rejected("candidate_time_not_rebound_to_earlier_episode", lambda: load_q16_bundle(contract_path, review_path))
        save(data)
        payload_path.write_text("{}")
        rejected("payload_tamper_rejected", lambda: load_q16_bundle(contract_path, review_path))
    summary = {"origin": "synthetic_integration", "tests": results,
               "passed": len(results), "failed": 0, "eligible_empirical_episodes": 0,
               "producer_fixture_contract_sha256": sha256(fixtures / "q16_synthetic_contract.json"),
               "producer_agreement": "T-008 explicitly confirmed separate Q16 projection is intended producer fixture shape"}
    (ROOT / "producer_integration_checks.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run()
