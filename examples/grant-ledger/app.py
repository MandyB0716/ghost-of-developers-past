"""List local grant applications; CSV export is unfinished."""

import argparse
import json
from pathlib import Path


DATA_FILE = Path(__file__).with_name("applications.json")


def load_applications():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def export_csv(applications, destination):
    # TODO: write organization, deadline, amount_requested, and status columns.
    raise NotImplementedError("CSV export has not been implemented yet.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, help="Save the applications as CSV")
    args = parser.parse_args()
    applications = load_applications()
    if args.export:
        export_csv(applications, args.export)
        return
    for application in sorted(applications, key=lambda item: item["deadline"]):
        print(f"{application['deadline']} | {application['organization']} | "
              f"${application['amount_requested']:,.0f} | {application['status']}")


if __name__ == "__main__":
    main()
