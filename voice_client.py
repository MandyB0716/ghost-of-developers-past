"""Manual ElevenLabs narration and short voice-goal transcription."""

import json
import os
import re
import secrets
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def api_key():
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise RuntimeError("ElevenLabs voice is not configured.")
    return key


def speech_text(markdown):
    text = re.sub(r"\[F\d+[^\]]*\]", "", markdown)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s+", "", text)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text or len(text) > 12000:
        raise ValueError("Narration needs 1-12,000 characters of analysis text.")
    return text


def send(request):
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read(15 * 1024 * 1024 + 1)
        if len(body) > 15 * 1024 * 1024:
            raise RuntimeError("The voice response was larger than this demo supports.")
        return body
    except HTTPError as error:
        detail = error.read(1500).decode("utf-8", errors="replace")
        detail = detail.replace(api_key(), "[REDACTED]")
        raise RuntimeError(f"ElevenLabs returned HTTP {error.code}: {detail}") from None


def narrate(markdown):
    text = speech_text(markdown)
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9]{10,64}", voice):
        raise RuntimeError("Choose an ElevenLabs narration voice before reading aloud.")
    payload = {"text": text, "model_id": os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")}
    request = Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{quote(voice)}?output_format=mp3_44100_128",
        data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"xi-api-key": api_key(), "Content-Type": "application/json"},
    )
    return send(request)


def transcribe(audio, content_type="audio/webm"):
    types = {"audio/webm": "goal.webm", "audio/ogg": "goal.ogg", "audio/mp4": "goal.m4a",
             "audio/mpeg": "goal.mp3", "audio/wav": "goal.wav", "audio/x-wav": "goal.wav"}
    content_type = content_type.split(";", 1)[0].strip().lower()
    if content_type not in types or not audio or len(audio) > 1500000:
        raise ValueError("Use a short audio recording under 1.5 MB.")
    boundary = "revival-" + secrets.token_hex(16)
    fields = {"model_id": os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2"),
              "tag_audio_events": "false", "timestamps_granularity": "none"}
    pieces = []
    for name, value in fields.items():
        pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    pieces.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                   f'filename="{types[content_type]}"\r\nContent-Type: {content_type}\r\n\r\n').encode())
    pieces.extend([audio, f"\r\n--{boundary}--\r\n".encode()])
    request = Request("https://api.elevenlabs.io/v1/speech-to-text", data=b"".join(pieces), method="POST",
                      headers={"xi-api-key": api_key(), "Content-Type": f"multipart/form-data; boundary={boundary}"})
    result = json.loads(send(request))
    text = result.get("text", "").strip()
    if not text:
        raise RuntimeError("No speech was recognized. Try again or type your goal.")
    return text
