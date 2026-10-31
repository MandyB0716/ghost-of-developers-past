"""Local project-revival workbench. Uploaded source is kept in memory only."""

import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, render_template, request, session
from dotenv import load_dotenv
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from gemma_client import ProviderBusyError, generate, grok_backup_enabled
from export_formats import filename, markdown_export, pdf_export
from project_reader import (EXCLUDED_FOLDERS, MANIFEST_NAMES, SENSITIVE_NAMES,
                            TEXT_NAMES, TEXT_SUFFIXES, collect_files, scan_project)
from revival_analysis import build_messages, build_revision_messages, check_references
from review_page import render_report, render_sources
from voice_client import narrate, transcribe


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def create_app(testing=False):
    app = Flask(__name__)
    hosted = os.environ.get("RENDER", "").lower() == "true"
    secret = os.environ.get("SECRET_KEY", "")
    if hosted and len(secret) < 32:
        raise RuntimeError("Set a generated SECRET_KEY of at least 32 characters in Render.")
    app.config.update(
        SECRET_KEY=secret or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=hosted,
        TESTING=testing,
        MODEL_CALL_LIMIT=40,
        VOICE_CALL_LIMIT=30,
        TRUSTED_HOSTS=["localhost", "127.0.0.1"] +
                      [h for h in [os.environ.get("RENDER_EXTERNAL_HOSTNAME")] if h],
    )
    workspaces, guard = OrderedDict(), threading.Lock()
    calls = 0
    voice_calls = 0

    @app.before_request
    def check_origin():
        if request.method == "POST" and request.headers.get("Origin"):
            if urlsplit(request.headers["Origin"]).netloc != request.host:
                return jsonify(error="Open the workbench directly before submitting files."), 403

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
        )
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="This selection is too large. Choose fewer source files."), 413

    @app.errorhandler(BadRequest)
    def bad_request(error):
        return jsonify(error=error.description), 400

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise BadRequest("Send a valid project selection.")
        return data

    def workspace():
        with guard:
            state = workspaces.get(session.get("workspace"))
            if not state or state["expires"] < time.monotonic():
                raise BadRequest("Review your project files before analyzing them.")
            state["expires"] = time.monotonic() + 3600
            return state

    def sources_for(state):
        return {f"F{i}": source for i, source in enumerate(state["snapshot"].files, 1)}

    def store_preview(snapshot, name):
        if not snapshot.files:
            raise BadRequest("No readable source files were selected.")
        key = secrets.token_urlsafe(24)
        state = {"snapshot": snapshot, "name": name[:100] or "Your project",
                 "history": [], "busy": False, "expires": time.monotonic() + 3600}
        with guard:
            workspaces.pop(session.get("workspace"), None)
            for old in list(workspaces):
                if workspaces[old]["expires"] < time.monotonic():
                    del workspaces[old]
            while len(workspaces) >= 24:
                workspaces.popitem(last=False)
            workspaces[key] = state
        session["workspace"] = key
        cards, options = render_sources(sources_for(state))
        return jsonify(name=state["name"], manifest=snapshot.manifest(),
                       source_html=cards, source_options=options,
                       files=[{"path": f.path, "text": f.text} for f in snapshot.files])

    def result_payload(state, index):
        if not isinstance(index, int) or not 0 <= index < len(state["history"]):
            raise BadRequest("Choose an available analysis version.")
        result = state["history"][index]
        return jsonify(report_html=render_report(result["content"], sources_for(state)),
                       version=index, versions=len(state["history"]),
                       seconds=result["seconds"], finish_reason=result["finish_reason"],
                       model=result.get("model", ""), fallback_used=result.get("fallback_used", False),
                       usage=result["usage"], reference_issues=result["reference_check"]["issues"])

    @app.get("/")
    def home():
        policy = {"excluded_folders": sorted(EXCLUDED_FOLDERS),
                  "sensitive_names": sorted(SENSITIVE_NAMES), "text_suffixes": sorted(TEXT_SUFFIXES),
                  "text_names": sorted(TEXT_NAMES | MANIFEST_NAMES), "manifests": sorted(MANIFEST_NAMES)}
        return render_template("workbench.html", reader_policy=policy,
                               voice_enabled=bool(os.environ.get("ELEVENLABS_API_KEY")),
                               grok_backup_enabled=grok_backup_enabled())

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.get("/api/example")
    def example():
        return store_preview(scan_project(ROOT / "examples" / "grant-ledger"), "Grant Ledger · example project")

    @app.post("/api/preview")
    def preview():
        data = payload()
        files = data.get("files")
        if not isinstance(files, list) or len(files) > 1000:
            raise BadRequest("Select at most 1,000 files for review.")
        if any(not isinstance(f, dict) or not isinstance(f.get("path"), str)
               or not isinstance(f.get("text"), str) for f in files):
            raise BadRequest("Each selected file needs a name and text content.")
        snapshot = collect_files((f["path"], f["text"].encode("utf-8")) for f in files)
        name = data.get("name", "Your project")
        return store_preview(snapshot, name if isinstance(name, str) else "Your project")

    def run_model(revision=False):
        nonlocal calls
        state, data = workspace(), payload()
        if revision:
            index = data.get("version", len(state["history"]) - 1)
            if not isinstance(index, int) or not 0 <= index < len(state["history"]):
                raise BadRequest("Generate an analysis before giving feedback.")
            previous = state["history"][index]
            feedback = data.get("feedback", "")
            if not isinstance(feedback, str):
                raise BadRequest("Write your feedback as text.")
            try:
                messages = build_revision_messages(previous["messages"], previous["content"], feedback)
            except ValueError as error:
                raise BadRequest(str(error)) from None
        else:
            goal = data.get("goal", "")
            if not isinstance(goal, str):
                raise BadRequest("Describe your restart goal as text.")
            try:
                messages = build_messages(state["snapshot"], goal)
            except ValueError as error:
                raise BadRequest(str(error)) from None
        with guard:
            if state["busy"]:
                return jsonify(error="Your analysis is already running."), 409
            if calls >= app.config["MODEL_CALL_LIMIT"]:
                return jsonify(error="This demo has reached its analysis allowance."), 429
            state["busy"] = True
            calls += 1
        try:
            result = generate(messages)
            result["reference_check"] = check_references(result["content"], state["snapshot"])
            result["messages"] = messages
            state["history"].append(result)
            return result_payload(state, len(state["history"]) - 1)
        except ProviderBusyError as error:
            return jsonify(error=str(error)), 429, {"Retry-After": str(error.retry_after)}
        except Exception as error:
            app.logger.warning("Model request failed: %s", type(error).__name__)
            message = re.sub(r"ya29\.[\w.~-]+|AIza[\w-]+", "[REDACTED]", str(error))
            return jsonify(error=message[:600] or "The model request did not complete."), 502
        finally:
            state["busy"] = False

    @app.post("/api/analyze")
    def analyze():
        return run_model()

    @app.post("/api/revise")
    def revise():
        return run_model(revision=True)

    @app.get("/api/version/<int:index>")
    def version(index):
        return result_payload(workspace(), index)

    def voice_allowance():
        nonlocal voice_calls
        with guard:
            if voice_calls >= app.config["VOICE_CALL_LIMIT"]:
                raise BadRequest("This demo has reached its voice allowance.")
            voice_calls += 1

    @app.post("/api/read-aloud")
    def read_aloud():
        state, data = workspace(), payload()
        index = data.get("version", len(state["history"]) - 1)
        if not isinstance(index, int) or not 0 <= index < len(state["history"]):
            raise BadRequest("Generate an analysis before reading it aloud.")
        result = state["history"][index]
        if "narration" not in result:
            voice_allowance()
            try:
                result["narration"] = narrate(result["content"])
            except Exception as error:
                return jsonify(error=str(error)[:600]), 502
        return Response(result["narration"], mimetype="audio/mpeg")

    @app.post("/api/transcribe")
    def transcribe_goal():
        audio = request.files.get("file")
        if audio is None:
            raise BadRequest("Record a goal before requesting transcription.")
        data = audio.read(1500001)
        if not data or len(data) > 1500000:
            raise BadRequest("Use a short audio recording under 1.5 MB.")
        voice_allowance()
        try:
            text = transcribe(data, audio.content_type or "audio/webm")
            return jsonify(text=text[:4000])
        except ValueError as error:
            raise BadRequest(str(error)) from None
        except Exception as error:
            return jsonify(error=str(error)[:600]), 502

    @app.get("/api/export")
    def export():
        state = workspace()
        raw_version = request.args.get("version", str(len(state["history"]) - 1))
        if not re.fullmatch(r"\d{1,5}", raw_version):
            raise BadRequest("Choose an available analysis version.")
        index = int(raw_version)
        if not 0 <= index < len(state["history"]):
            raise BadRequest("Generate an analysis before saving it.")
        extension = request.args.get("format", "md")
        if extension not in ("md", "pdf"):
            raise BadRequest("Choose Markdown or PDF.")
        result = state["history"][index]
        exporter = pdf_export if extension == "pdf" else markdown_export
        content = exporter(result["content"], result["messages"], state["name"], index)
        return Response(content, mimetype="application/pdf" if extension == "pdf" else "text/markdown",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{filename(state["name"], index, extension)}"'})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), debug=False)
