"""Make one short request to Google's managed Gemma API using an existing login."""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gemma_client import MODEL, cloud_value, generate


def check_connection(project):
    result = generate(
        [{"role": "user", "content": "Reply with exactly: Ready to help revive a software project."}],
        project=project, max_tokens=64, attempts=1,
    )
    return {
        "success": True, "response": result["content"], "returned_model": result["model"],
        "finish_reason": result["finish_reason"], "usage": result["usage"],
        "seconds": result["seconds"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Google Cloud project ID; defaults to gcloud's active project")
    args = parser.parse_args()
    report = {"model": MODEL, "tested_at": datetime.now(timezone.utc).isoformat()}
    try:
        project = args.project or cloud_value("config", "get-value", "project")
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project or ""):
            raise RuntimeError("Select a valid Google Cloud project before testing.")
        report["project"] = project
        report.update(check_connection(project))
    except HTTPError as exc:
        report.update(success=False, http_status=exc.code, error=exc.read(16384).decode("utf-8", errors="replace"))
    except (RuntimeError, URLError, TimeoutError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        report.update(success=False, error=str(exc))
    # Store only the result: no request headers, access tokens, or credential files.
    output = json.dumps(report, indent=2, ensure_ascii=False)
    output = re.sub(r"ya29\.[A-Za-z0-9._~-]+|AIza[A-Za-z0-9_-]+", "[REDACTED]", output)
    name = "gemma-connection-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
    path = ROOT / "test" / "test-data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
