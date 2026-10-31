import io
import json
import os
import unittest
from unittest.mock import patch

from app import create_app
from voice_client import narrate, speech_text, transcribe


class VoiceTests(unittest.TestCase):
    def test_narration_omits_citation_labels_without_modifying_analysis(self):
        original="## Project\nUse **CSV** in `app.py` [F1:L1, F2:L2]."
        spoken=speech_text(original)
        self.assertNotIn("F1:L1",spoken)
        self.assertIn("Use CSV in app.py",spoken)
        self.assertIn("[F1:L1",original)

    @patch.dict(os.environ,{"ELEVENLABS_API_KEY":"test-key","ELEVENLABS_VOICE_ID":"EXAVITQu4vr4xnSDxMaL"})
    def test_output_format_is_query_parameter_not_model_payload(self):
        with patch("voice_client.send",return_value=b"mp3") as send:
            self.assertEqual(narrate("A short explanation."),b"mp3")
        request=send.call_args.args[0]
        self.assertIn("?output_format=mp3_44100_128",request.full_url)
        self.assertNotIn("output_format",json.loads(request.data))

    @patch.dict(os.environ,{"ELEVENLABS_API_KEY":"test-key"})
    def test_transcription_uses_the_documented_file_field(self):
        with patch("voice_client.send",return_value=b'{"text":"Finish the export."}') as send:
            self.assertEqual(transcribe(b"synthetic-audio","audio/webm"),"Finish the export.")
        body=send.call_args.args[0].data
        self.assertIn(b'name="file"',body)
        self.assertNotIn(b'name="audio"',body)

    def test_oversized_audio_is_rejected_before_provider_request(self):
        with patch("voice_client.send") as send:
            with self.assertRaises(ValueError):transcribe(b"a"*1500001)
        send.assert_not_called()

    def test_read_aloud_reuses_audio_for_same_analysis(self):
        client=create_app(testing=True).test_client();client.get("/api/example")
        result={"content":"An explanation [F1:L1].","seconds":0,"finish_reason":"stop","usage":{}}
        with patch("app.generate",return_value=result):client.post("/api/analyze",json={"goal":"Review."})
        with patch("app.narrate",return_value=b"audio") as speak:
            self.assertEqual(client.post("/api/read-aloud",json={"version":0}).status_code,200)
            self.assertEqual(client.post("/api/read-aloud",json={"version":0}).status_code,200)
        self.assertEqual(speak.call_count,1)

    def test_transcription_returns_editable_text_without_calling_gemma(self):
        client=create_app(testing=True).test_client()
        with patch("app.transcribe",return_value="Finish CSV export."),patch("app.generate") as model:
            result=client.post("/api/transcribe",data={"file":(io.BytesIO(b"synthetic-audio"),"goal.webm","audio/webm")})
        self.assertEqual(result.get_json()["text"],"Finish CSV export.")
        model.assert_not_called()


if __name__=="__main__":
    unittest.main()
