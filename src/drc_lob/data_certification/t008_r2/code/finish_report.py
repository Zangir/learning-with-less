"""Wait for the bounded capture, then validate and render the evidence bundle."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
deadline = time.monotonic() + 900
while time.monotonic() < deadline:
    try:
        status = json.loads((ROOT / "evidence/live_capture_status.json").read_text())
    except json.JSONDecodeError:
        time.sleep(1)
        continue
    if status["status"] == "completed":
        break
    if status["status"] == "stopped":
        raise RuntimeError("Capture stopped early; do not render completed-source claims")
    time.sleep(10)
else:
    raise TimeoutError("Capture finalization deadline reached")
for script in ("live_snapshot_contract.py", "render_report.py"):
    subprocess.run([sys.executable, str(ROOT / "code" / script)], check=True)
print("NORMALIZATION_AND_RENDER_COMPLETE", flush=True)
