"""Run the curated historical implementation with package-local paths."""
from pathlib import Path
import runpy
import sys

PACKAGE = Path(__file__).resolve().parent
SOURCE = PACKAGE / 'src/pilot.py'
for path in (PACKAGE / "src", SOURCE.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
runpy.run_path(str(SOURCE), run_name="__main__")
