# Project Revival Workbench

[Ghost of Developers Past on GitHub](https://github.com/MandyB0716/ghost-of-developers-past)

[Try the live workbench](https://ghost-of-developers-past.onrender.com/)

A new Hacktoberfest Week 4 project to help developers return to unfinished software.
The core workflow reads selected project files, uses Gemma to explain the evidence,
and creates a restart plan with references to the original files. Developers can
submit feedback, compare versions, and save a restart plan as Markdown or PDF.

## Run the local workbench

From PowerShell in this folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -B .\app.py
```

Open `http://127.0.0.1:8765/` in Edge. Try the example or click **Open project folder**.
Choose the project's top-level folder and confirm the folder selection; there is
no need to remember or select individual source files. Supported browsers use a
read-only directory picker, excluding credential and generated folders before
visiting their contents. Other browsers fall back to a directory upload control.
Individual file selection is available under an optional disclosure. The prepared
file list opens automatically for review. Cancelling the picker keeps the current
review, and choosing a folder does not make a model request.
Review the selected files, inspect their text in **Sources**, and return to
**Project** to click **Build my restart plan**. Loading or previewing files makes
no model request. An analysis or
an explicitly submitted feedback revision calls the managed Gemma API.

The example is **Grant Ledger**, a fictional unfinished tracker used to test the
workbench. It is separate from the Project Revival application.

Project text and analysis versions are kept in the server process's memory, not
written to uploaded project files or an uploads directory. Workspaces expire
after an hour of inactivity and disappear when the server stops. Expired entries
are removed when another snapshot is prepared; closing a tab does not immediately
remove its server workspace. **Clear session** explicitly removes the current
browser's workspace, including its snapshot, response history and cached narration,
and clears its session cookie. Download your plan first. It leaves original project
files and downloaded plans untouched and does not reset demo usage allowances.
Other open workbench tabs receive a reset notification when BroadcastChannel is
available. This does not recall requests already sent to cloud providers or control
their retention policies. **Save plan**,
below the response, downloads the selected version as Markdown or PDF, with a
file-and-line reference list. It does not append source text, prompts, or feedback.
Exports are generated locally without another AI request. Whole-file citations
are identified as such, and unresolved locations are not assigned invented lines.
Review pattern-based redactions before sending private code to the cloud.

The local app loads this project's ignored `.env` without overriding process
environment variables. It uses your existing Google Cloud CLI login and active
project unless `GOOGLE_CLOUD_PROJECT` is set. For now it allows at most
40 analysis operations per server process. This is a local development server.
The public app runs on Render; for production startup and hosted authentication, see
[Render deployment](docs/DEPLOYMENT.md) for the exact settings and remaining
credential and live-verification steps.

## Current component: model connection diagnostic

`test/test-scripts/check_gemma.py` makes one short request to the managed Gemma 4 26B API.
It uses your existing Google Cloud CLI sign-in, limits output to 64 tokens,
and saves a result in the ignored `test/test-data/` folder. It does not print tokens,
deploy a GPU, change billing settings, or read another project's source files.

From PowerShell in this folder:

```powershell
.\.venv\Scripts\python.exe -B .\test\test-scripts\check_gemma.py --project high-sunlight-512802-k0
```

The connection test needs the Google Cloud CLI, an existing sign-in, and access
to the managed model in the selected project. No Python packages are required
for this component. Each run makes one billable API request if Google accepts it.

### Verified connection

On October 29, 2026 (Central time), the first request returned HTTP 429 with
"The request queue is full." A later single retry succeeded, returning:

> Ready to help revive a software project.

The successful request used 25 input tokens and 9 output tokens and completed
in 0.64 seconds. This verifies connectivity for this small request, not the
model's ability to analyze a real project. Both diagnostic results are saved
locally under the ignored `test/test-data/` directory.

## Project-file reader

`project_reader.py` builds a local preview of a selected folder. It does not run
code, modify the selected project, or contact an AI provider. It prefers the root
README, dependency manifests, and source code before other documents, and accepts
at most 40 text files, 64 KiB per file, and 160,000 bytes of prepared text in total.
The preview reports which files were excluded and why. PDF and notebook parsing
are not part of this first component.

Credential files, generated folders, symbolic links, and junctions are excluded.
Recognized credential-like strings in source are replaced while preserving their
line numbers. Pattern matching cannot identify every possible secret: users will
review selected content before any cloud analysis is connected.

```powershell
.\.venv\Scripts\python.exe .\project_reader.py "C:\path\to\unfinished-project"
.\.venv\Scripts\python.exe -B -m unittest discover -s .\test\test-scripts -p "test_project_reader.py" -v
```

The command prints file metadata and exclusion reasons, not source contents.
The same reader can also accept selected files from the future browser interface.

## First Gemma project analysis

`revival_analysis.py` gives Gemma a bounded snapshot and the developer's restart
goal. Files are numbered as evidence, and the response is preserved unchanged.
The local reference check validates source IDs and line ranges; it does not
establish that a citation supports a claim. We review that together.

Shared model instructions live in `prompts/revival-rules.md`. The application
loads this trusted file into system messages for new analyses and revisions;
Grok receives the same reviewed evidence and rules if the bounded fallback is
needed. It is not a fine-tuning dataset, and uploaded project instructions never
replace it. The rules require comparing setup/startup commands with supplied
entry files and manifests, asking for essential missing information, and using
the viewer's supported file-and-line citation syntax. Instructions guide model
behavior; they do not prove that every claim is correct.

The included `examples/grant-ledger` is a small unfinished demonstration project,
not an existing nonprofit system. Its sample records are fictional. The reader
does not execute this project. To repeat the analysis:

```powershell
.\.venv\Scripts\python.exe .\revival_analysis.py .\examples\grant-ledger --goal "Help me finish a first usable version with CSV export. Keep it local and simple."
```

Each analysis makes a managed API request with up to 2,200 output tokens. The
shared `gemma_client.py` makes at most three Gemma attempts for transient HTTP errors
or network timeouts (the initial attempt plus two retries),
waiting about 5-6 seconds and then 10-11 seconds between attempts. It honors a
provider's longer `Retry-After` delay up to 30 seconds; a longer cooldown returns
control to the user without retrying early. Retries use a 180-second window and
up to 90 seconds per network attempt when backup is disabled. With backup enabled,
Gemma's per-attempt timeout is 40 seconds, leaving time for one Grok attempt with
up to 60 seconds or the remaining window, whichever is smaller. Authentication
errors are not retried.
A full queue produces a readable service-busy message and preserves the source
snapshot and previous response versions. It never requests a rewritten answer.

### Optional Grok backup

Gemma remains the primary model. The optional backup is Google Cloud's managed
`xai/grok-4.20-non-reasoning` API, using the same project and authentication.
It is **off by default**: set `ENABLE_GROK_BACKUP=true` only after confirming
access to Grok and reviewing its example response. No GPU deployment is needed.

With the backup enabled, an operation uses at most three Gemma attempts followed
by one Grok attempt for timeouts or transient HTTP failures (429, 500, 502, 503, or 504).
Both models share a four-attempt maximum and a 180-second retry window. Provider
cooldowns are respected; a cooldown above 30 seconds ends the operation without
switching models. Authentication failures, non-timeout network errors, and
empty responses do not trigger fallback. A successful response is preserved
exactly; factual quality issues require the developer's explicit feedback.
Grok is used only for that one response, with no background inference or dedicated
deployment. The next analysis or revision starts with Gemma again. A timeout
does not prove the provider stopped processing the earlier request; retries can
therefore incur additional model charges.

The Project tab discloses the additional model destination when backup is
enabled. Each response version identifies whether Gemma or the Grok backup
answered. Selected files are sent to Grok only if the backup is enabled and
the transient-error path reaches its final attempt. Model charges follow
Google's current prices; promotional-credit coverage has not been verified.

The isolated comparison script makes one Grok request against the original,
frozen fictional Grant Ledger prompt, saving its exact response, source-linked
review, usage, and diagnostics in ignored test data:

```powershell
.\.venv\Scripts\python.exe -B .\test\test-scripts\compare_grok.py
```

On October 30, 2026 (Central), this comparison completed in 12.41 seconds and
identified the startup mismatch and unfinished CSV export. It returned 709
output tokens from 1,409 input tokens, with an estimated model charge of
$0.00353375 before any credit adjustment. Source-location checks passed; this
does not establish factual support or overall quality. Mandy reviewed and approved
this response and Grok's role as the backup on October 30. This is one exploratory result,
not a benchmark or a guarantee of availability.

Inputs, the raw response, usage, finish
reason, and reference diagnostics are saved in a unique ignored `test/test-data/analyses/`
folder. This does not store authentication headers or access tokens.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s .\test\test-scripts -p "test_*.py" -v
node --test .\test\test-scripts\test_project_folder.cjs .\test\test-scripts\test_source_navigation.cjs .\test\test-scripts\test_session_controls.cjs
```

## Clickable source review

`review_page.py` creates a self-contained HTML view of a saved analysis. Clicking
a reference selects the corresponding source file and highlights the cited lines.
Source text comes from the saved input, so citations stay attached to the version
Gemma actually read. The original `analysis.md` is not changed.

Line references highlight the stated range. Whole-file references such as `[F5]`
are labeled `(file)` and open that file without claiming a line location. A file
range such as `[F14-F22]` expands only when every file exists in the supplied
snapshot. Invalid line references stay unavailable rather than falling back to
an unrelated location. None of these navigation checks verifies claim support.

```powershell
.\.venv\Scripts\python.exe .\review_page.py .\test\test-data\analyses\RUN-FOLDER --title "Project review"
```

Open the generated `review.html` manually in Edge or another browser. The saved
review makes no network calls. The page uses a small escaped Markdown formatter
for headings, paragraphs, lists, emphasis, and inline code; it does not execute
HTML supplied by the model or project files.

The project picker, analysis, feedback history, saved handoffs, source-linked
review, and ElevenLabs voice are implemented. Public Render deployment and
verification are still pending.

## Missing information and developer answers

Both models receive the same instruction to ask for essential missing details
instead of inventing requirements or answers. They should ask at most three
focused questions, identify decisions that depend on the answers, and leave
those decisions pending. Evidence-backed work can proceed. They should not ask
filler questions, repeat answers already provided, or request secrets.

Below a response, **Answer questions or request changes** opens automatically.
The developer supplies answers and clicks **Update restart plan**. Only that
explicit action makes another model request. The selected version's original
files, goal, questions, and earlier answers stay in context, and the old version
remains available. Developer-supplied facts should be identified as such rather
than assigned fabricated file citations. These instructions reduce unsupported
assumptions; they are not an automatic factual-verification system.

## ElevenLabs voice

Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in the ignored `.env` file or
hosting environment. The initial configured voice is Sarah. TTS uses
`eleven_flash_v2_5`; transcription uses `scribe_v2`.

- **Read aloud** narrates the selected analysis, omitting citation labels from
  speech without modifying the written answer. **Stop audio** stops playback.
- Generated narration is cached in the workspace's memory for that analysis
  version, so replaying it does not require another provider call.
- **Speak your goal** records microphone audio after the user grants browser
  permission. **Stop and transcribe** sends it to ElevenLabs and fills the editable
  goal field. It never automatically sends the transcript to Gemma.
- Recordings stop after 90 seconds and are limited to 1.5 MB. Microphone tracks
  are stopped after recording and when leaving the page.
- Voice requests are manual and the local demo allows at most 30 provider voice
  requests per server process. Audio and source files are processed by the
  respective cloud providers only for the actions the user selects.

The synthetic voice check passed on October 30, 2026 (Central time): ElevenLabs
generated a short test sentence and transcribed the same words back. Browser
microphone recording, transcription, narration, and stopping playback were also
confirmed by Mandy in Edge on October 30, 2026.

## Project layout

```text
Week4DevChallenge/
  app.py                  Web application and review workflow
  gemma_client.py         Managed Gemma connection
  cloud_auth.py           Local CLI or hosted Google authentication
  gunicorn.conf.py        One production worker and four request threads
  project_reader.py       Source selection and redaction
  revival_analysis.py     Evidence prompts and feedback context
  review_page.py          Source-linked saved reviews
  export_formats.py       Markdown and PDF plans without source appendices
  voice_client.py         ElevenLabs speech services
  examples/               Fictional demonstration projects
  static/                 Browser scripts and styles
  templates/              Interface templates
  deploy/                 Reviewable cloud-role definition, without keys
  docs/                   Deployment instructions
  test/
    README.md             Test commands and diagnostic notes
    test-scripts/         Automated tests and connection diagnostic
    test-data/            Ignored local results and saved reviews
```

The ignored `.env` and `.venv/` stay at the project root. Existing test outputs
were moved without changing their contents. See `test/README.md` for the complete
test commands and the local Google Cloud permission requirement.

## Interface

Mandy tested the source-linked review and chose three tabs on October 30, 2026:

- **Project** holds folder selection, file approval, and the editable restart goal.
- **Restart plan** holds the response, versions, voice, saving, and feedback.
- **Sources** provides full-width browsing of the prepared file snapshot.
- Clicking a reference opens the shared source viewer beside the restart plan.
- Make references clickable, showing file names and line numbers.
- Selecting a reference switches to its source file and highlights the exact range.
- Keep the source-file dropdown for browsing the evidence independently.
- Display the frozen source text the model read, preserving the reference locations.
- Use a glossy black backdrop and controls, translucent orange glass panels,
  bright orange outlines and buttons, white text, and the ghost in front of the
  transparent gothic bookshelf.
- Clearly identify the project being evaluated, including whether it is a sample.
- Add the project picker, analysis controls, feedback, and voice around this layout.
- Preserve original model responses when presenting revisions.
- Keep Markdown/PDF controls after the response; save the selected version and
  its reference list only.

## Challenge

[Hacktoberfest Week 4: Ghost in the Machine](https://dev.to/challenges/hacktoberfest-week4-2026-10-26)

Our interpretation is recovering the context and unfinished intentions left in
old software. The workbench itself is new work; old projects will be test inputs.

Original code: [MIT license](LICENSE). See [NOTICE.md](NOTICE.md) for artwork and
dependency licensing notes.
