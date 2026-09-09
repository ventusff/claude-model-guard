#!/usr/bin/env python3
"""Bootstrap from a checkout or a Codex plugin cache, using Python's standard library."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_guard.install import main

if __name__ == "__main__":
    sys.exit(main())
