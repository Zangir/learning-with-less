"""Prove the run_day copy differs only at declared orchestration/storage nodes."""
import ast
import inspect
import unittest
from t016_p3.extraction import run_day as original
from t016_p5.extraction import run_day as compact

def scientific_body(function):
    node=ast.parse(inspect.getsource(function)).body[0]
    output=[]
    for statement in node.body:
        if isinstance(statement,ast.Assign):
            names={target.id for target in statement.targets if isinstance(target,ast.Name)}
            if names & {'source_id','provenance_path','retained_records','serialized_bound','array_bound'}:
                continue
        if isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Call):
            call=statement.value
            if isinstance(call.func,ast.Name) and call.func.id=='resources': continue
            if isinstance(call.func,ast.Name) and call.func.id in ('dump_lines','dump_json'):
                if any(isinstance(x,ast.Constant) and x.value in
                       ('source-row-provenance.jsonl','source-provenance-reference.json') for x in ast.walk(call.args[0])):
                    continue
        output.append(statement)
    node.body=output
    return ast.dump(node,include_attributes=False)

class TestOrchestration(unittest.TestCase):
    def test_only_source_identity_and_storage_nodes_change(self):
        self.assertEqual(scientific_body(original),scientific_body(compact))

if __name__=='__main__': unittest.main()
