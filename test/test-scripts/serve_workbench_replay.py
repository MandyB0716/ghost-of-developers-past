"""Browser QA using two saved example responses; never calls an AI provider."""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app import create_app


runs = ROOT / "test" / "test-data" / "analyses"
responses = [
    (runs / "20261030T033123342723Z" / "analysis.md").read_text(encoding="utf-8"),
    (runs / "20261030T035111155078Z-revision" / "analysis.md").read_text(encoding="utf-8"),
]
index = 0


def replay(messages):
    global index
    text = responses[min(index, 1)]
    index += 1
    return {"content":text,"seconds":0,"finish_reason":"stop","usage":{}}


app = create_app(testing=True)


@app.after_request
def identify_replay(response):
    if response.mimetype == "text/html":
        page = response.get_data(as_text=True).replace(
            "<body>", '<body><p class="preview-banner">SAVED EXAMPLE REPLAY - No new AI calls. Use Grant Ledger only.</p>')
        response.set_data(page)
    return response


if __name__ == "__main__":
    with patch("app.generate", side_effect=replay):
        app.run(host="127.0.0.1", port=8768, debug=False)
