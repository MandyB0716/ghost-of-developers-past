"""Small Google Cloud Gemma client with bounded retries and no credential logging."""

import json
import math
import os
import random
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cloud_auth import access_token


MODEL = "google/gemma-4-26b-a4b-it-maas"
BACKUP_MODEL = "xai/grok-4.20-non-reasoning"
RETRY_WINDOW_SECONDS = 180
PRIMARY_TIMEOUT_SECONDS = 40
BACKUP_TIMEOUT_SECONDS = 60


class ProviderBusyError(RuntimeError):
    def __init__(self, retry_after=None):
        self.retry_after = max(1, math.ceil(retry_after or 30))
        super().__init__(
            "The cloud model service is busy right now. Please try again later. "
            "Your selected files and any previous plans are still available."
        )


def retry_after_seconds(value):
    """Read a provider delay without treating an invalid header as a command."""
    if not value or len(value) > 100:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, seconds) if math.isfinite(seconds) else None


def cloud_value(*arguments):
    executable = shutil.which("gcloud")
    if not executable:
        raise RuntimeError("Google Cloud CLI was not found on PATH.")
    result = subprocess.run(
        [executable, "--quiet", *arguments], capture_output=True, text=True,
        timeout=40, stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        detail = result.stderr.strip()
        if any(marker in detail.lower() for marker in ("permission denied", "access is denied", "winerror 5")):
            raise RuntimeError(
                "The local app cannot access your Google Cloud login files. "
                "Restart the workbench with access to your gcloud configuration folder, "
                "then review your selected files again. You do not need a new API key."
            )
        raise RuntimeError(detail or "Google Cloud CLI could not complete the command.")
    return result.stdout.strip()


def grok_backup_enabled():
    return os.environ.get("ENABLE_GROK_BACKUP", "false").strip().lower() == "true"


def generate(messages, *, project=None, max_tokens=2200, attempts=3, allow_backup=None):
    project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        if os.environ.get("RENDER", "").lower() == "true":
            raise ValueError("Set GOOGLE_CLOUD_PROJECT in Render before generating.")
        project = cloud_value("config", "get-value", "project")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project or ""):
        raise ValueError("Select a valid Google Cloud project before generating.")
    if not 1 <= max_tokens <= 4096 or not 1 <= attempts <= 3:
        raise ValueError("Request budget is outside the supported limits.")
    token = access_token(lambda: cloud_value("auth", "print-access-token"))
    if not token:
        raise RuntimeError("Google Cloud CLI returned no access token.")
    endpoint = (f"https://aiplatform.googleapis.com/v1/projects/{project}"
                "/locations/global/endpoints/openapi/chat/completions")
    use_backup = grok_backup_enabled() if allow_backup is None else bool(allow_backup)
    total_attempts = attempts + int(use_backup)
    attempted_models = []
    started = time.monotonic()
    for attempt in range(total_attempts):
        model = MODEL if attempt < attempts else BACKUP_MODEL
        remaining = RETRY_WINDOW_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise RuntimeError("The cloud request reached its retry time limit. Please try again later.")
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": False}
        if model == MODEL:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        attempted_models.append(model)
        limit = BACKUP_TIMEOUT_SECONDS if model == BACKUP_MODEL else (
            PRIMARY_TIMEOUT_SECONDS if use_backup else 90)
        try:
            with urlopen(request, timeout=min(limit, remaining)) as response:
                result = json.load(response)
            break
        except HTTPError as exc:
            retry_after = retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None)
            try:
                detail = exc.read(16384).decode("utf-8", errors="replace")
            finally:
                exc.close()
            error = (ProviderBusyError(retry_after) if exc.code == 429 else
                     RuntimeError(f"Google Cloud returned HTTP {exc.code}: {detail}"))
            if exc.code not in {429, 500, 502, 503, 504}:
                raise error from None
        except (TimeoutError, URLError) as exc:
            if isinstance(exc, URLError) and not isinstance(exc.reason, TimeoutError):
                raise
            retry_after = None
            error = RuntimeError(
                "The model request timed out. Please try again later. "
                "Your selected files and any previous plans are still available."
            )
        if model == BACKUP_MODEL or attempt + 1 >= total_attempts:
            raise error from None
        # The backup gets exactly one attempt. Every new operation starts with
        # Gemma; a fallback never changes the default model or starts a worker.
        switching_to_backup = attempt + 1 == attempts
        delay = (retry_after or 0) if switching_to_backup else max(
            5 * 2 ** attempt + random.uniform(0, 1), retry_after or 0)
        remaining = RETRY_WINDOW_SECONDS - (time.monotonic() - started)
        if delay > 30 or remaining <= delay + 1:
            raise error from None
        if delay:
            time.sleep(delay)
    choice = (result.get("choices") or [{}])[0]
    content = choice.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The model returned no text.")
    return {
        "content": content, "model": result.get("model", model), "project": project,
        "fallback_used": model == BACKUP_MODEL, "attempted_models": attempted_models,
        "finish_reason": choice.get("finish_reason"), "usage": result.get("usage"),
        "seconds": round(time.monotonic() - started, 2), "attempts": attempt + 1,
    }
