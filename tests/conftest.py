import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("STEAMSHELF_DATA_DIR", tempfile.mkdtemp(prefix="shelf-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
