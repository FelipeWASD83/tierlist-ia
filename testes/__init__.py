"""Tests run with `python -m unittest discover -s testes -t .` from the project folder."""

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent / "servidor"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
