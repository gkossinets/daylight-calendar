import sys
from pathlib import Path

# The tool is a single script, not a package; make it importable from tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
