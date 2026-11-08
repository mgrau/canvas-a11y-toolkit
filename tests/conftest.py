import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["CANVAS_WORKSPACE"] = str(HERE / "workspace")
os.environ["CANVAS_TOKEN"] = "test-token-not-real"
sys.path.insert(0, str(HERE.parent / "scripts"))
