"""One bounded Grok request using the original frozen Grant Ledger example."""

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gemma_client import cloud_value
from project_reader import ProjectSnapshot
from review_page import render_page, source_snapshot
from revival_analysis import check_references

PROJECT = "high-sunlight-512802-k0"
MODEL = "xai/grok-4.20-non-reasoning"
FROZEN = ROOT / "test/test-data/analyses/20261030T033123342723Z/input.json"


def redact(value):
    return re.sub(r"ya29\.[A-Za-z0-9._~-]+|AIza[A-Za-z0-9_-]+", "[REDACTED]", value)


def main():
    original = FROZEN.read_bytes()
    messages = json.loads(original.decode("utf-8"))
    sources, goal = source_snapshot(messages)
    if (len(original) > 16000 or len(messages) != 2 or
            {s.path for s in sources.values()} != {"README.md", "app.py", "applications.json"} or
            "# Grant Ledger" not in next(s.text for s in sources.values() if s.path == "README.md")):
        raise ValueError("This diagnostic only accepts the frozen fictional Grant Ledger example.")
    output = ROOT / "test/test-data/analyses" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-grok")
    output.mkdir(parents=True, exist_ok=False)
    (output / "input.json").write_bytes(original)
    report = {
        "success": False, "project": PROJECT, "model": MODEL, "region": "global",
        "max_tokens": 2200, "attempts": 1,
        "input_sha256": hashlib.sha256(original).hexdigest(),
        "comparison_to": "20261030T033123342723Z", "credit_eligibility": "not verified",
        "sampling": "provider default; one exploratory comparison, not a benchmark",
    }
    started = time.monotonic()
    try:
        token = cloud_value("auth", "print-access-token")
        if not token:
            raise RuntimeError("Google Cloud CLI returned no access token.")
        endpoint = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}"
                    "/locations/global/endpoints/openapi/chat/completions")
        request = Request(
            endpoint,
            data=json.dumps({"model": MODEL, "messages": messages,
                             "max_tokens": 2200, "stream": False}).encode("utf-8"),
            method="POST", headers={"Authorization": f"Bearer {token}",
                                    "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=90) as response:
            raw = json.load(response)
        choice = raw["choices"][0]
        content = choice.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Grok returned no response text.")
        report.update(
            success=True, returned_model=raw.get("model"), usage=raw.get("usage"),
            finish_reason=choice.get("finish_reason"),
            reference_check=check_references(content, ProjectSnapshot(list(sources.values()), [])),
        )
        usage = report["usage"] or {}
        report["estimated_model_cost_usd"] = (
            usage.get("prompt_tokens", 0) * 1.25 + usage.get("completion_tokens", 0) * 2.50
        ) / 1000000
        (output / "analysis.md").write_text(content, encoding="utf-8")
        (output / "response.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
        (output / "review.html").write_text(
            render_page(content, messages, "Grok 4.20 - Grant Ledger comparison"), encoding="utf-8")
    except HTTPError as error:
        try:
            report.update(http_status=error.code,
                          error=redact(error.read(12000).decode("utf-8", errors="replace")))
        finally:
            error.close()
    except (RuntimeError, URLError, TimeoutError, ValueError, KeyError, OSError) as error:
        report["error"] = redact(str(error))
    report["seconds"] = round(time.monotonic() - started, 2)
    (output / "run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "reference_check"}, indent=2))
    print(f"Saved to: {output}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
