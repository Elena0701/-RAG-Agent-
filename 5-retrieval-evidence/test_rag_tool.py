"""Compatibility test runner; maintained tests live under tests/."""
from pathlib import Path
import unittest

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
