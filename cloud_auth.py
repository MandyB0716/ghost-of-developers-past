"""Google authentication for local CLI use and hosted runtime credentials."""

import hashlib
import json
import os
import threading

import google.auth
import requests
from google.auth.transport.requests import Request as AuthRequest
from google.oauth2 import service_account


SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_guard = threading.Lock()
_credentials = None
_source = None


class BoundedAuthRequest(AuthRequest):
    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = 20
        return super().__call__(*args, **kwargs)


def access_token(local_token_loader):
    """Keep hosted credentials and authentication failures out of logs."""
    global _credentials, _source
    credential_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    credential_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    hosted = os.environ.get("RENDER", "").lower() == "true"
    if not (hosted or credential_path or credential_json):
        return local_token_loader()
    if not (credential_path or credential_json):
        raise RuntimeError(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON in Render, or point "
            "GOOGLE_APPLICATION_CREDENTIALS to a Render secret file."
        )
    if credential_path and credential_json:
        raise RuntimeError("Choose one Google credential method: JSON environment value or secret file.")
    source = ("file", credential_path) if credential_path else (
        "json", hashlib.sha256(credential_json.encode("utf-8")).hexdigest())
    try:
        with _guard:
            if _credentials is None or _source != source:
                if credential_json:
                    info = json.loads(credential_json)
                    if not isinstance(info, dict) or info.get("type") != "service_account":
                        raise ValueError("Expected a dedicated service account.")
                    credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
                else:
                    credentials, _ = google.auth.default(scopes=SCOPES)
                _credentials, _source = credentials, source
            if not _credentials.valid:
                with requests.Session() as session:
                    _credentials.refresh(BoundedAuthRequest(session=session))
            token = _credentials.token
            if not isinstance(token, str) or not token:
                raise ValueError("Authentication returned no token.")
            return token
    except Exception:
        raise RuntimeError(
            "Google Cloud authentication could not complete. Check the dedicated "
            "service-account credential and its access to the configured project."
        ) from None
