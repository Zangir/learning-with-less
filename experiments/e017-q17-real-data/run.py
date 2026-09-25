"""Run the reviewed Q17 completion from a package-local frozen plan."""
from pathlib import Path
import sys

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE / "src"))
from completion.q17_runs import run

PLAN = PACKAGE / "config" / "run-plan.json"
run(PLAN, PACKAGE / "runtime" / "cache", PACKAGE / "runtime" / "output")
