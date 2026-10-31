import io
import json
import subprocess
import unittest
from email.message import Message
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from gemma_client import BACKUP_MODEL, MODEL, ProviderBusyError, cloud_value, generate, retry_after_seconds
from project_reader import collect_files
from revival_analysis import RULES_PATH, build_messages


class CloudLoginTests(unittest.TestCase):
    def test_access_denied_explains_recovery_without_dumping_local_credential_details(self):
        failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="Unable to create private file credentials.db: [WinError 5] Access is denied",
        )
        with patch("gemma_client.shutil.which", return_value="gcloud"), \
                patch("gemma_client.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "Restart the workbench") as raised:
                cloud_value("auth", "print-access-token")
        self.assertNotIn("credentials.db", str(raised.exception))
        self.assertIn("do not need a new API key", str(raised.exception))


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0
        self.delays = []
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", {"ENABLE_GROK_BACKUP": "false"}).start()
        patch("gemma_client.cloud_value", return_value="synthetic-token").start()
        patch("gemma_client.random.uniform", return_value=0.25).start()
        patch("gemma_client.time.monotonic", side_effect=lambda:self.clock).start()
        patch("gemma_client.time.sleep", side_effect=self.sleep).start()

    def sleep(self, delay):
        self.delays.append(delay)
        self.clock += delay

    @staticmethod
    def failure(code=429, retry_after=None):
        headers = Message()
        if retry_after:
            headers["Retry-After"] = retry_after
        return HTTPError("https://example.invalid", code, "test error", headers,
                         io.BytesIO(b'{"error":{"message":"The request queue is full."}}'))

    @staticmethod
    def response():
        return io.BytesIO(json.dumps({"choices":[{"message":{"content":"Saved plan"},
                            "finish_reason":"stop"}],"usage":{}}).encode())

    def test_two_busy_responses_then_success_have_bounded_spaced_retries(self):
        with patch("gemma_client.urlopen", side_effect=[self.failure(), self.failure(), self.response()]) as send:
            result = generate([], project="test-project")
        self.assertEqual(send.call_count, 3)
        self.assertEqual(self.delays, [5.25, 10.25])
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["content"], "Saved plan")

    def test_exhausted_queue_returns_a_friendly_error_and_stops(self):
        with patch("gemma_client.urlopen", side_effect=[self.failure() for _ in range(3)]) as send:
            with self.assertRaises(ProviderBusyError) as raised:
                generate([], project="test-project")
        self.assertEqual(send.call_count, 3)
        self.assertNotIn("RESOURCE_EXHAUSTED", str(raised.exception))
        self.assertIn("selected files", str(raised.exception))

    def test_provider_retry_after_is_respected(self):
        with patch("gemma_client.urlopen", side_effect=[self.failure(retry_after="17"), self.response()]):
            generate([], project="test-project")
        self.assertEqual(self.delays, [17])

    def test_long_provider_cooldown_does_not_hold_the_browser_or_retry_early(self):
        with patch("gemma_client.urlopen", side_effect=self.failure(retry_after="300")) as send:
            with self.assertRaises(ProviderBusyError) as raised:
                generate([], project="test-project")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.delays, [])
        self.assertEqual(raised.exception.retry_after, 300)

    def test_retry_window_prevents_another_attempt(self):
        with patch("gemma_client.RETRY_WINDOW_SECONDS", 8), \
                patch("gemma_client.urlopen", side_effect=[self.failure(), self.failure()]) as send:
            with self.assertRaises(ProviderBusyError):
                generate([], project="test-project")
        self.assertEqual(send.call_count, 2)
        self.assertEqual(self.delays, [5.25])
        self.assertAlmostEqual(send.call_args.kwargs["timeout"], 2.75)

    def test_auth_errors_are_not_retried(self):
        with patch("gemma_client.urlopen", side_effect=self.failure(403)) as send:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                generate([], project="test-project")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.delays, [])

    def test_temporary_server_failure_can_recover_without_changing_models(self):
        with patch("gemma_client.urlopen", side_effect=[self.failure(503), self.response()]) as send:
            result = generate([], project="test-project")
        self.assertEqual(send.call_count, 2)
        self.assertEqual(self.delays, [5.25])
        self.assertEqual(result["model"], "google/gemma-4-26b-a4b-it-maas")

    def test_header_dates_and_invalid_values_are_handled(self):
        date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20), usegmt=True)
        self.assertTrue(18 <= retry_after_seconds(date) <= 20)
        for value in (None, "invalid", "NaN", "inf", "x" * 101):
            self.assertIsNone(retry_after_seconds(value))

    def test_enabled_backup_keeps_successful_primary_response_unchanged(self):
        with patch("gemma_client.urlopen", return_value=self.response()) as send:
            result = generate([], project="test-project", allow_backup=True)
        self.assertEqual(send.call_count, 1)
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["attempted_models"], [MODEL])

    def test_backup_uses_the_same_messages_without_gemma_specific_options(self):
        messages = build_messages(collect_files([("app.py", b"print('example')\n")]), "Review this project.")
        with patch("gemma_client.urlopen", side_effect=[self.failure(), self.failure(), self.failure(), self.response()]) as send:
            result = generate(messages, project="test-project", allow_backup=True)
        bodies = [json.loads(call.args[0].data) for call in send.call_args_list]
        self.assertEqual([body["model"] for body in bodies], [MODEL, MODEL, MODEL, BACKUP_MODEL])
        self.assertTrue(all(body["messages"] == messages for body in bodies))
        self.assertEqual(bodies[3]["messages"][0]["content"], RULES_PATH.read_text(encoding="utf-8").strip())
        self.assertIn("chat_template_kwargs", bodies[0])
        self.assertNotIn("chat_template_kwargs", bodies[3])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["model"], BACKUP_MODEL)
        self.assertEqual(result["content"], "Saved plan")
        self.assertEqual(result["attempts"], 4)
        self.assertEqual(self.delays, [5.25, 10.25])

    def test_backup_failure_does_not_start_another_retry_loop(self):
        with patch("gemma_client.urlopen", side_effect=[self.failure() for _ in range(4)]) as send:
            with self.assertRaises(ProviderBusyError):
                generate([], project="test-project", allow_backup=True)
        models = [json.loads(call.args[0].data)["model"] for call in send.call_args_list]
        self.assertEqual(models, [MODEL, MODEL, MODEL, BACKUP_MODEL])

    def test_long_cooldown_stops_before_switching_to_backup(self):
        with patch("gemma_client.urlopen", side_effect=self.failure(retry_after="300")) as send:
            with self.assertRaises(ProviderBusyError):
                generate([], project="test-project", allow_backup=True)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.delays, [])

    def test_auth_failure_never_switches_to_backup(self):
        with patch("gemma_client.urlopen", side_effect=self.failure(403)) as send:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                generate([], project="test-project", allow_backup=True)
        self.assertEqual(send.call_count, 1)

    def test_backup_shares_the_original_time_budget(self):
        with patch("gemma_client.RETRY_WINDOW_SECONDS", 8), \
                patch("gemma_client.urlopen", side_effect=[self.failure(), self.failure()]) as send:
            with self.assertRaises(ProviderBusyError):
                generate([], project="test-project", allow_backup=True)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(self.delays, [5.25])

    def test_two_timeout_retries_then_one_backup_and_next_request_starts_with_gemma(self):
        models, timeouts = [], []
        def request(request, *, timeout):
            models.append(json.loads(request.data)["model"])
            timeouts.append(timeout)
            if len(models) <= 3:
                self.clock += timeout
                raise TimeoutError("Read timed out")
            return self.response()
        with patch("gemma_client.urlopen", side_effect=request):
            fallback = generate([], project="test-project", allow_backup=True)
            next_request = generate([], project="test-project", allow_backup=True)
        self.assertEqual(models, [MODEL, MODEL, MODEL, BACKUP_MODEL, MODEL])
        self.assertTrue(fallback["fallback_used"])
        self.assertEqual(fallback["attempts"], 4)
        self.assertFalse(next_request["fallback_used"])
        self.assertEqual(next_request["attempts"], 1)
        self.assertEqual(timeouts[:3], [40, 40, 40])
        self.assertAlmostEqual(timeouts[3], 44.5)
        self.assertEqual(self.delays, [5.25, 10.25])

    def test_wrapped_network_timeouts_also_reach_the_single_backup(self):
        with patch("gemma_client.urlopen", side_effect=[
                URLError(TimeoutError("timed out")) for _ in range(3)] + [self.response()]) as send:
            result = generate([], project="test-project", allow_backup=True)
        self.assertEqual(send.call_count, 4)
        self.assertTrue(result["fallback_used"])

    def test_other_network_errors_are_not_treated_as_timeouts(self):
        with patch("gemma_client.urlopen", side_effect=URLError("certificate verify failed")) as send:
            with self.assertRaises(URLError):
                generate([], project="test-project", allow_backup=True)
        self.assertEqual(send.call_count, 1)

    def test_missing_text_does_not_trigger_an_automatic_rewrite(self):
        empty = io.BytesIO(b'{"choices":[{"message":{"content":""}}]}')
        with patch("gemma_client.urlopen", return_value=empty) as send:
            with self.assertRaisesRegex(RuntimeError, "returned no text"):
                generate([], project="test-project", allow_backup=True)
        self.assertEqual(send.call_count, 1)

    def test_explicit_environment_opt_in_respects_the_primary_attempt_budget(self):
        with patch.dict("os.environ", {"ENABLE_GROK_BACKUP":"true"}), \
                patch("gemma_client.urlopen", side_effect=[self.failure(503), self.failure(503), self.response()]) as send:
            result = generate([], project="test-project", attempts=2)
        self.assertEqual(send.call_count, 3)
        self.assertEqual(result["attempted_models"], [MODEL, MODEL, BACKUP_MODEL])


if __name__ == "__main__":
    unittest.main()
