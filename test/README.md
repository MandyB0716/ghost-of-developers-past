# Tests and saved test runs

Run the commands below from the project root.

- `test-scripts/` contains automated Python and JavaScript tests, plus the
  explicitly invoked live Gemma connection diagnostic.
- `test-data/` contains local test outputs, audio checks, raw model responses,
  and saved source-linked reviews. Its contents are ignored by Git except for
  the empty-directory placeholder. Saved reviews can contain selected source code.

## Automated tests

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s .\test\test-scripts -p "test_*.py" -v
node --test .\test\test-scripts\test_project_folder.cjs .\test\test-scripts\test_source_navigation.cjs
```

Automated tests use synthetic inputs and mocked provider calls. They do not send
a project to Gemma or use the live ElevenLabs API.

## Live Gemma connection diagnostic

```powershell
.\.venv\Scripts\python.exe -B .\test\test-scripts\check_gemma.py --project high-sunlight-512802-k0
```

This diagnostic makes one short, billable managed-model request. It saves the
result to a dated `test/test-data/gemma-connection-*.json` file without saving
access tokens or overwriting previous results.

The local workbench uses your existing Google Cloud CLI login. The process must
be able to write to `%APPDATA%\gcloud` for token refreshes and CLI logs. If Codex
launches the server, that directory must be included in the launch permissions;
no Windows permission changes, credential copying, or new keys are needed.

## Saved-review navigation preview

```powershell
.\.venv\Scripts\python.exe -B .\test\test-scripts\preview_saved_review.py .\test\test-data\REVIEW.html .\test\test-data\NEW-PREVIEW.html
```

This creates a separate copy with updated styles, source navigation, and links
for known file-only citations. It preserves the saved prose and embedded source
blocks, makes no AI request, and refuses to overwrite either an original or an
existing destination. It does not correct the model's factual claims or citations
that point to the wrong lines.

## Tabbed interface and exports

Queue/capacity tests simulate temporary failures and successful recovery without
calling Google. They cover bounded retries, increasing waits, provider cooldowns,
authentication failures, and preservation of the source snapshot and plan history.
Optional Grok backup tests also cover a shared attempt/time budget, unchanged
evidence, provider-specific request options, no fallback after authentication
errors or non-timeout network failures, and model identity retained per response version.
Timeout simulations cover an initial Gemma attempt, two Gemma retries, one Grok
response, and a new request returning to Gemma. Follow-up tests check that user
answers are sent only after submission and retained across subsequent revisions.
The separate `test-scripts/compare_grok.py` diagnostic makes one live request
with the saved fictional fixture; it is never run by automated test discovery.

The working app uses Project / Restart plan / Sources tabs. Automated export
checks cover selected versions, missing or invalid references, literal markup,
safe filenames, session isolation, and exclusion of source text from exports.
The PDF uses ReportLab's bundled Vera fonts and requires no external rendering
service. Manual browser checks used the isolated replay below, then inspected
the downloaded PDF and rendered both pages of the revised example.

```powershell
.\.venv\Scripts\python.exe -B .\test\test-scripts\serve_workbench_replay.py
```

This optional QA server at port 8768 replays two saved Grant Ledger responses
from ignored local test data. Its banner identifies it as a replay; it does not
call Gemma. The saved runs must exist locally. Use it only with the fictional
example. Normal app startup remains `app.py` on port 8765.
