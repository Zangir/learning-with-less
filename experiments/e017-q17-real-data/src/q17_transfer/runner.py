"""Origin-preserving producer integration and the fixed Q17 historical pilot."""
from pathlib import Path
from .gate import implementation_sha256, sha256
from .pilot import fit_evaluate, require_fit_runtime, write_json
from .producer import load_contract, prepare_asset, TRANSFER
from .protocol import PROTOCOL, digest_json

HISTORICAL_SPLITS = {"train": "2025-12-08", "validation": "2025-12-16", "test": "2025-12-23"}
HISTORICAL_POLICY = dict(version="2.1.1", clock_scope="exchange_time", continuity="sampled_snapshots",
    max_age_ns=1_500_000_000, max_gap_ns=2_000_000_000,
    source_revision="855468264d219c3c67677b8fc1e5ace06cb26e57", split_dates=HISTORICAL_SPLITS, asset="BTC", hour="00")


def run_producer(contract_path, expected_sha256, expected_origin, output_dir, asset="BTC", split_dates=None, predeclaration=None):
    """Fit the immutable producer payload; a result never grants scientific acceptance.

    Invoke within the task's detached resource guard. Real date roles must be
    fixed before results, and remain distinct from the original eight-day gate.
    """
    require_fit_runtime()
    paths = [contract_path] if isinstance(contract_path, (str, Path)) else contract_path
    hashes = [expected_sha256] if isinstance(expected_sha256, str) else expected_sha256
    if len(paths) != len(hashes) or any(sha256(p) != h for p, h in zip(paths, hashes)):
        raise ValueError("Producer contract differs from frozen input hash")
    if expected_origin != "synthetic_integration" and split_dates != HISTORICAL_SPLITS:
        raise ValueError("Real pilot requires the predeclared historical date roles")
    if expected_origin != "synthetic_integration" and predeclaration is None:
        raise ValueError("Real pilot requires an archived predeclaration file")
    panels = [load_contract(path, expected_origin) for path in paths]
    acquisition_bindings = [{k: v for k, v in p["contract"].items() if k.startswith(("acquisition_", "supersedes_"))} for p in panels]
    loaded = panels[0]
    for panel in panels[1:]:
        for field in ("schema", "version", "origin", "purpose", "units", "scopes", "horizons", "policy_sha256"):
            if loaded["contract"].get(field) != panel["contract"].get(field):
                raise ValueError("Inconsistent panel policy: "+field)
        for field in ("kind", "max_age_ns", "max_gap_ns"):
            if loaded["contract"]["continuity"].get(field) != panel["contract"]["continuity"].get(field):
                raise ValueError("Inconsistent panel continuity: "+field)
        if {s["source_id"] for s in loaded["contract"]["sources"]} & {s["source_id"] for s in panel["contract"]["sources"]}:
            raise ValueError("Duplicate panel source identity")
        loaded["rows"].extend(panel["rows"])
        loaded["windows"].extend(panel["windows"])
        loaded["contract"]["sources"].extend(panel["contract"]["sources"])
    if expected_origin != "synthetic_integration":
        import numpy as np
        from .features import NS, DAY
        if asset != "BTC":
            raise ValueError("Historical pilot is predeclared BTC only")
        contract = loaded["contract"]
        if (contract["version"] != HISTORICAL_POLICY["version"] or contract["scopes"]["Q17"]["clock_scope"] != HISTORICAL_POLICY["clock_scope"]
                or contract["continuity"]["kind"] != HISTORICAL_POLICY["continuity"]
                or any(contract["continuity"].get(k) != HISTORICAL_POLICY[k] for k in ("max_age_ns", "max_gap_ns"))
                or any(s.get("source_revision") != HISTORICAL_POLICY["source_revision"] for s in contract["sources"])):
            raise ValueError("Historical producer differs from predeclared freshness, clock or source policy")
        selected_days = {int(np.datetime64(date, "ns").astype(np.int64)) for date in split_dates.values()}
        for window in loaded["windows"]:
            if window["asset"] == asset and window["start_ns"]//DAY*DAY in selected_days:
                if window["end_ns"] > window["start_ns"]//DAY*DAY+3600*NS:
                    raise ValueError("Historical pilot permits only predeclared hour00 windows")
    arrays, diagnostics = prepare_asset(loaded, asset, split_dates)
    context = dict(origin=expected_origin, asset=asset, split_dates=split_dates,
        scope="Source-pinned Q17 sampled-state pilot; descriptive single-asset evaluation",
        independent_test_days=1 if split_dates and expected_origin != "synthetic_integration" else 0,
        feature_clock_scope=loaded["contract"]["scopes"]["Q17"]["clock_scope"],
        observation_model=TRANSFER["sampled_observation_model"],
        eligibility_conditioning="Retrospective common support/freshness mask; not an online guarantee of future coverage",
        exchange_time_assumption=TRANSFER["exchange_clock"],
        historical_receipt_claim=False, observed_fills=False, reviewer_acceptance="not issued by this runner",
        freeze_checks=diagnostics["freeze_checks"],
        provenance=dict(producer_sha256=hashes, mapping_sha256=loaded["mapping_sha256"],
            implementation_sha256=implementation_sha256(), protocol_sha256=digest_json(PROTOCOL),
            historical_policy_sha256=digest_json(HISTORICAL_POLICY) if split_dates else None,
            predeclaration_sha256=sha256(predeclaration) if predeclaration else None,
            acquisition_bindings=acquisition_bindings,
            sources=loaded["contract"]["sources"]))
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):
        result = fit_evaluate(arrays, output_dir, context)
    write_json(Path(output_dir)/"projection_diagnostics.json", diagnostics)
    write_json(Path(output_dir)/"mapping.json", TRANSFER)
    return result
