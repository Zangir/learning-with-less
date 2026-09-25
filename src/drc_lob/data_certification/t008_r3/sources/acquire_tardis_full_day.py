"""Run only the predeclared full-day expansion through the bounded downloader."""
from pathlib import Path
import acquire_tardis_panel as acquisition

BASE = Path(__file__).resolve().parent
acquisition.PLAN = BASE / "tardis_full_day_preflight.json"
acquisition.AUTH = BASE / "tardis_full_day_authorization.json"
acquisition.OUT = BASE / "tardis_full_day"
acquisition.main()
