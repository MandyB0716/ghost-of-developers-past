import unittest
from unittest.mock import patch

from app import create_app
from gemma_client import ProviderBusyError


def answer():
    return {"content":"## Where to restart\nInspect the startup command [F1:L9].", "model":"test-model",
            "seconds":0.1,"finish_reason":"stop","usage":{"prompt_tokens":10,"completion_tokens":10}}


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.app=create_app(testing=True)
        self.client=self.app.test_client()

    def test_home_and_example_do_not_call_the_model(self):
        with patch("app.generate") as model:
            self.assertEqual(self.client.get("/").status_code,200)
            preview=self.client.get("/api/example").get_json()
        model.assert_not_called()
        self.assertEqual(preview["manifest"]["file_count"],3)
        self.assertIn('source-F1-L9',preview["source_html"])

    def test_health_check_does_not_call_a_provider(self):
        with patch("app.generate") as model, patch("app.narrate") as voice:
            response = self.client.get("/healthz")
        self.assertEqual(response.get_json(), {"status":"ok"})
        model.assert_not_called()
        voice.assert_not_called()

    def test_render_requires_a_long_session_secret(self):
        with patch.dict("os.environ", {"RENDER":"true", "SECRET_KEY":"short"}):
            with self.assertRaisesRegex(RuntimeError, "generated SECRET_KEY"):
                create_app(testing=True)

    def test_render_uses_secure_cookies_and_its_own_hostname(self):
        with patch.dict("os.environ", {"RENDER":"true", "SECRET_KEY":"synthetic-session-secret-for-tests-only", 
                                     "RENDER_EXTERNAL_HOSTNAME":"example.onrender.com"}):
            hosted = create_app(testing=True).test_client()
            response = hosted.get("/api/example", base_url="https://example.onrender.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["Set-Cookie"])

    def test_analysis_requires_a_reviewed_snapshot(self):
        self.assertEqual(self.client.post("/api/analyze",json={"goal":"Review."}).status_code,400)

    def test_uploaded_credentials_are_excluded_and_paths_cannot_escape(self):
        response=self.client.post("/api/preview",json={"files":[
            {"path":".env","text":"PASSWORD=private"},
            {"path":"../secret.py","text":"private"},
            {"path":"app.py","text":"print('hello')"}]})
        data=response.get_json()
        self.assertEqual(data["manifest"]["file_count"],1)
        self.assertNotIn("PASSWORD",data["source_html"])
        self.assertEqual(len(data["manifest"]["skipped"]),2)

    def test_feedback_and_original_versions_are_preserved(self):
        self.client.get("/api/example")
        with patch("app.generate",return_value=answer()) as model:
            first=self.client.post("/api/analyze",json={"goal":"Finish CSV export."})
            revised=self.client.post("/api/revise",json={"version":0,"feedback":"Check startup."})
        self.assertEqual(first.get_json()["version"],0)
        self.assertEqual(revised.get_json()["versions"],2)
        messages=model.call_args.args[0]
        self.assertEqual(messages[-1],{"role":"user","content":"Check startup."})
        self.assertIn("Finish CSV export.",messages[1]["content"])
        self.assertEqual(self.client.get("/api/version/0").get_json()["version"],0)
        self.assertEqual(self.client.get("/api/export?version=0").status_code,200)

    def test_other_browser_session_cannot_export_a_project(self):
        self.client.get("/api/example")
        with patch("app.generate",return_value=answer()):
            self.client.post("/api/analyze",json={"goal":"Finish CSV export."})
        other=self.app.test_client()
        self.assertEqual(other.get("/api/export").status_code,400)

    def test_exports_preserve_sources_with_trailing_blank_lines(self):
        self.client.post("/api/preview", json={"files":[
            {"path":"app.py", "text":"print('ready')\n\n\n\n"}]})
        result = {**answer(), "content":"Inspect the entry file [F1:L1-L3]."}
        with patch("app.generate", return_value=result):
            self.client.post("/api/analyze", json={"goal":"Review the entry file."})
        markdown = self.client.get("/api/export?format=md")
        self.assertEqual(markdown.status_code, 200)
        self.assertIn(b"app.py, lines 1-3", markdown.data)
        pdf = self.client.get("/api/export?format=pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF-"))

    def test_busy_service_preserves_the_snapshot_and_previous_plan(self):
        self.client.get("/api/example")
        with patch("app.generate", side_effect=[ProviderBusyError(), answer(),
                   ProviderBusyError(45), answer()]):
            failed = self.client.post("/api/analyze",json={"goal":"Finish CSV export."})
            self.assertEqual(failed.status_code,429)
            original = self.client.post("/api/analyze",json={"goal":"Finish CSV export."})
            self.assertEqual(original.get_json()["version"],0)
            failed_revision = self.client.post("/api/revise",json={"version":0,"feedback":"Check startup."})
            self.assertEqual(failed_revision.status_code,429)
            self.assertEqual(failed_revision.headers["Retry-After"],"45")
            self.assertIn("selected files",failed_revision.get_json()["error"])
            saved = self.client.get("/api/version/0").get_json()
            self.assertEqual(saved["versions"],1)
            self.assertIn("Inspect the startup command",saved["report_html"])
            self.assertEqual(self.client.get("/api/export?version=0").status_code,200)
            revised = self.client.post("/api/revise",json={"version":0,"feedback":"Check startup."})
        self.assertEqual(revised.get_json()["versions"],2)

    def test_project_root_is_not_a_public_static_folder(self):
        self.assertEqual(self.client.get("/.env").status_code,404)
        self.assertEqual(self.client.get("/gemma_client.py").status_code,404)

    def test_each_saved_version_retains_its_model_identity(self):
        self.client.get("/api/example")
        primary = {**answer(), "model":"google/gemma-4-26b-a4b-it-maas", "fallback_used":False}
        backup = {**answer(), "model":"xai/grok-4.20-non-reasoning", "fallback_used":True}
        with patch("app.generate", side_effect=[primary, backup]):
            first = self.client.post("/api/analyze", json={"goal":"Finish CSV export."}).get_json()
            revised = self.client.post("/api/revise", json={"feedback":"Check startup."}).get_json()
        self.assertFalse(first["fallback_used"])
        self.assertTrue(revised["fallback_used"])
        self.assertEqual(revised["model"], backup["model"])
        self.assertFalse(self.client.get("/api/version/0").get_json()["fallback_used"])
        self.assertTrue(self.client.get("/api/version/1").get_json()["fallback_used"])

    def test_backup_data_destination_is_disclosed_only_when_enabled(self):
        with patch.dict("os.environ", {"ENABLE_GROK_BACKUP":"false"}):
            self.assertNotIn(b"same reviewed files may go to Grok", self.client.get("/").data)
        with patch.dict("os.environ", {"ENABLE_GROK_BACKUP":"true"}):
            self.assertIn(b"same reviewed files may go to Grok", self.client.get("/").data)

    def test_cross_origin_posts_are_rejected(self):
        response=self.client.post("/api/preview",json={"files":[]},headers={"Origin":"https://unrelated.example"})
        self.assertEqual(response.status_code,403)

    def test_clear_session_removes_snapshot_history_narration_and_cookie(self):
        self.client.get("/api/example")
        original_cookie = self.client.get_cookie("session").value
        with patch("app.generate", return_value=answer()), patch("app.narrate", return_value=b"synthetic-audio"):
            self.client.post("/api/analyze", json={"goal":"Finish CSV export."})
            self.assertEqual(self.client.post("/api/read-aloud", json={"version":0}).status_code, 200)
        cleared = self.client.post("/api/session/clear", json={})
        self.assertEqual(cleared.get_json(), {"cleared":True})
        self.assertIsNone(self.client.get_cookie("session"))
        # Even a saved copy of the former signed cookie cannot restore the data.
        self.client.set_cookie("session", original_cookie)
        with patch("app.generate") as model, patch("app.narrate") as voice:
            self.assertEqual(self.client.get("/api/version/0").status_code, 400)
            self.assertEqual(self.client.get("/api/export?version=0").status_code, 400)
            self.assertEqual(self.client.post("/api/read-aloud", json={"version":0}).status_code, 400)
            self.assertEqual(self.client.post("/api/analyze", json={"goal":"Resume."}).status_code, 400)
        model.assert_not_called()
        voice.assert_not_called()

    def test_clear_session_does_not_affect_another_visitor(self):
        other = self.app.test_client()
        self.client.get("/api/example")
        other.get("/api/example")
        with patch("app.generate", side_effect=lambda *args: answer()):
            self.client.post("/api/analyze", json={"goal":"My plan."})
            other.post("/api/analyze", json={"goal":"Other visitor's plan."})
        self.client.post("/api/session/clear", json={})
        self.assertEqual(other.get("/api/version/0").status_code, 200)
        self.assertEqual(other.get("/api/export").status_code, 200)

    def test_clear_waits_for_an_inflight_analysis(self):
        self.client.get("/api/example")
        second_tab = self.app.test_client()
        second_tab.set_cookie("session", self.client.get_cookie("session").value)
        def during_generation(*args):
            blocked = second_tab.post("/api/session/clear", json={})
            self.assertEqual(blocked.status_code, 409)
            return answer()
        with patch("app.generate", side_effect=during_generation):
            self.assertEqual(self.client.post("/api/analyze", json={"goal":"Review."}).status_code, 200)
        self.assertEqual(self.client.get("/api/version/0").status_code, 200)
        self.assertEqual(second_tab.post("/api/session/clear", json={}).status_code, 200)
        self.assertEqual(self.client.get("/api/version/0").status_code, 400)

    def test_clear_does_not_reset_shared_demo_allowances(self):
        self.app.config.update(MODEL_CALL_LIMIT=1, VOICE_CALL_LIMIT=1)
        self.client.get("/api/example")
        with patch("app.generate", side_effect=lambda *args: answer()), patch("app.narrate", return_value=b"audio"):
            self.client.post("/api/analyze", json={"goal":"First plan."})
            self.client.post("/api/read-aloud", json={"version":0})
            self.client.post("/api/session/clear", json={})
            self.client.get("/api/example")
            self.assertEqual(self.client.post("/api/analyze", json={"goal":"New plan."}).status_code, 429)
        from io import BytesIO
        with patch("app.transcribe") as speech:
            self.assertEqual(self.client.post("/api/transcribe", data={"file":(BytesIO(b"audio"),"goal.webm")}).status_code, 400)
        speech.assert_not_called()

    def test_clear_requires_same_origin_json_and_is_safe_to_repeat(self):
        self.client.get("/api/example")
        self.assertEqual(self.client.get("/api/session/clear").status_code, 405)
        self.assertEqual(self.client.post("/api/session/clear", data={}).status_code, 400)
        self.assertEqual(self.client.post("/api/session/clear", json={}, headers={"Origin":"https://unrelated.example"}).status_code, 403)
        self.assertIsNotNone(self.client.get_cookie("session"))
        with patch("app.generate") as model, patch("app.narrate") as voice:
            self.assertEqual(self.client.post("/api/session/clear", json={}).status_code, 200)
            self.assertEqual(self.client.post("/api/session/clear", json={}).status_code, 200)
        model.assert_not_called()
        voice.assert_not_called()

    def test_answers_to_questions_are_sent_only_when_submitted_and_retained(self):
        self.client.get("/api/example")
        question = {**answer(), "content":"## Questions for the developer\nWhich hosting service does your course require?"}
        supplied = "My course requires Render. The runtime must be Python 3.11."
        followup = "Keep the suggested changes small."
        with patch("app.generate", side_effect=[question, answer(), answer()]) as model:
            original = self.client.post("/api/analyze", json={"goal":"Prepare the course deployment."})
            self.assertIn("Which hosting service", original.get_json()["report_html"])
            self.assertEqual(model.call_count, 1)
            self.client.post("/api/revise", json={"version":0,"feedback":supplied})
            self.client.post("/api/revise", json={"version":1,"feedback":followup})
        first_context = model.call_args_list[0].args[0]
        final_context = model.call_args_list[2].args[0]
        self.assertNotIn(supplied, [m["content"] for m in first_context])
        self.assertIn({"role":"user","content":supplied}, final_context)
        self.assertEqual(final_context[-1], {"role":"user","content":followup})
        self.assertEqual(final_context[:2], first_context)
        self.assertIn("Which hosting service", self.client.get("/api/version/0").get_json()["report_html"])


if __name__=="__main__":
    unittest.main()
