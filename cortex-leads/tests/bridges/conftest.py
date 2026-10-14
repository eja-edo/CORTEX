import sys
from pathlib import Path

# `bridges/` is not part of the installed package; make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
