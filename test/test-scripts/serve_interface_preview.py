"""Serve an isolated, example-only interface preview; no provider calls."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flask import Flask, render_template_string, send_from_directory
from project_reader import scan_project
from review_page import render_report, render_sources


DESIGN = ROOT / "test" / "test-data" / "interface-preview"
app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/shared")


@app.get("/")
def preview():
    snapshot = scan_project(ROOT / "examples" / "grant-ledger")
    sources = {f"F{i}": source for i, source in enumerate(snapshot.files, 1)}
    cards, options = render_sources(sources)
    runs = ROOT / "test" / "test-data" / "analyses"
    original = (runs / "20261030T033123342723Z" / "analysis.md").read_text(encoding="utf-8")
    revision = (runs / "20261030T035111155078Z-revision" / "analysis.md").read_text(encoding="utf-8")
    return render_template_string(
        (DESIGN / "index.html").read_text(encoding="utf-8"),
        original_report=render_report(original, sources), report=render_report(revision, sources),
        source_cards=cards, source_options=options, files=snapshot.manifest()["files"],
    )


@app.get("/design/<path:name>")
def design_asset(name):
    return send_from_directory(DESIGN, name)


@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8766, debug=False)
