"""Add immutable receipt-provenance bindings without rewriting issued contracts."""
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import paired_normalize as N


def bind_contract(path):
    path = Path(path)
    output = path.with_name("shared_data_contract.v2.2.1.json")
    if output.exists():
        raise ValueError("Bound contract already exists")
    contract = json.loads(path.read_text())
    contract.update(version="2.2.1", supersedes_contract_file=path.name, supersedes_contract_sha256=N.P.sha256(path),
        source_provenance_file="source_provenance.jsonl", source_provenance_sha256=N.P.sha256(path.parent / "source_provenance.jsonl"))
    contract["sources"][0].update(source_provenance_file="source_provenance.jsonl", source_provenance_sha256=contract["source_provenance_sha256"])
    contract["evidence_files"] = {name:N.P.sha256(path.parent / name) for name in
        ("eligibility_diagnostics.json","clock_diagnostics.json","grid_audit.csv","q17_required_cut_audit.csv","q18_endpoint_audit.csv","duplicate_ledger.json")}
    N.write_json(output, contract)
    return output


def bind_index(index_path):
    index_path = Path(index_path)
    index = json.loads(index_path.read_text())
    replacements = {}
    for asset in index["contracts"]:
        path = bind_contract(asset["contract_file"])
        updated = deepcopy(asset)
        updated.update(contract_file=str(path), contract_sha256=N.P.sha256(path))
        replacements[(asset["date"], asset["asset"])] = updated
    bound = deepcopy(index)
    bound.update(version="2.2.1", supersedes_index_file=index_path.name, supersedes_index_sha256=N.P.sha256(index_path))
    bound["contracts"] = list(replacements.values())
    for day in bound["dates"]:
        day["assets"] = [replacements[(day["date"], asset["asset"])] for asset in day["assets"]]
    output = index_path.with_name("dataset_index.v2.2.1.json")
    if output.exists():
        raise ValueError("Bound dataset index already exists")
    N.write_json(output, bound)
    return output


def main():
    schema = json.loads((N.ROOT / "interface/shared_data_contract.v2.2.0.schema.json").read_text())
    schema["title"] = "T-008 paired sampled snapshot producer contract2.2.1 with bound receipt provenance"
    schema["properties"]["version"] = {"const":"2.2.1"}
    schema["required"].extend(["supersedes_contract_file","supersedes_contract_sha256","source_provenance_file","source_provenance_sha256"])
    N.write_json(N.ROOT / "interface/shared_data_contract.v2.2.1.schema.json", schema)
    output = bind_index(N.ROOT / "interface/hour00/dataset_index.v2.2.0.json")
    print(json.dumps({"index":str(output),"sha256":N.P.sha256(output)}))


if __name__ == "__main__":
    main()
