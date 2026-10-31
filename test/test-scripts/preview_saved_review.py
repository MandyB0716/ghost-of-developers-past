"""Make a separate navigation preview of a saved workbench review; no AI calls."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_page import refresh_saved_navigation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(refresh_saved_navigation(arguments.source, arguments.destination), indent=2))
