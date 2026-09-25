from pathlib import Path
import sys

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
REPOSITORY_SRC = Path(__file__).resolve().parents[3] / "src"
for path in (PACKAGE_SRC, REPOSITORY_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

MODULE = PACKAGE_SRC / "q16_transfer"
if MODULE.is_dir():
    sys.path.insert(0, str(MODULE))
