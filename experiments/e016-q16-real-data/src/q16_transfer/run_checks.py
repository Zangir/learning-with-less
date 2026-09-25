"""Write auditable invariant-test output beside this configured entry point."""
import contextlib
import json
import platform
import time
import unittest
from pathlib import Path

import test_adapter

HERE = Path(__file__).resolve().parent


def main():
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_adapter)
    with (HERE / "checks.log").open("w") as stream, contextlib.redirect_stdout(stream):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    summary = {"tests_run": result.testsRun, "passed": result.wasSuccessful(),
               "failures": len(result.failures), "errors": len(result.errors),
               "python": platform.python_version(), "platform": platform.platform(),
               "seconds": time.monotonic() - started,
               "scope": "Constructed invariant and certification-gate fixtures only"}
    (HERE / "checks.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
