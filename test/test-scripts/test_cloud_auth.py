import json
import unittest
from unittest.mock import Mock, patch

import requests

from cloud_auth import BoundedAuthRequest, access_token


class HostedAuthTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", {}, clear=True).start()
        patch("cloud_auth._credentials", None).start()
        patch("cloud_auth._source", None).start()

    def test_local_login_remains_the_existing_cli_login(self):
        local = Mock(return_value="synthetic-local-token")
        self.assertEqual(access_token(local), "synthetic-local-token")
        local.assert_called_once_with()

    def test_render_without_credentials_never_tries_to_run_gcloud(self):
        local = Mock()
        with patch.dict("os.environ", {"RENDER":"true"}):
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_SERVICE_ACCOUNT_JSON"):
                access_token(local)
        local.assert_not_called()

    def test_json_credential_refresh_is_cached_and_never_uses_cli(self):
        local = Mock()
        credentials = Mock(valid=False, token=None)
        def refresh(request):
            credentials.token = "synthetic-hosted-token"
            credentials.valid = True
        credentials.refresh.side_effect = refresh
        info = {"type":"service_account", "private_key":"synthetic-not-a-key"}
        with patch.dict("os.environ", {"RENDER":"true", "GOOGLE_SERVICE_ACCOUNT_JSON":json.dumps(info)}), \
                patch("cloud_auth.service_account.Credentials.from_service_account_info", return_value=credentials) as load:
            self.assertEqual(access_token(local), "synthetic-hosted-token")
            self.assertEqual(access_token(local), "synthetic-hosted-token")
        load.assert_called_once()
        credentials.refresh.assert_called_once()
        local.assert_not_called()

    def test_secret_file_uses_adc_without_printing_or_loading_the_file_into_app_code(self):
        credentials = Mock(valid=True, token="synthetic-adc-token")
        local = Mock()
        with patch.dict("os.environ", {"GOOGLE_APPLICATION_CREDENTIALS":"/etc/secrets/gcp-service-account.json"}), \
                patch("cloud_auth.google.auth.default", return_value=(credentials, "test-project")) as load:
            self.assertEqual(access_token(local), "synthetic-adc-token")
        load.assert_called_once()
        credentials.refresh.assert_not_called()
        local.assert_not_called()

    def test_credential_failure_does_not_expose_its_private_details(self):
        with patch.dict("os.environ", {"GOOGLE_SERVICE_ACCOUNT_JSON":'{"type":"service_account"}'}), \
                patch("cloud_auth.service_account.Credentials.from_service_account_info",
                      side_effect=ValueError("private_key=SENSITIVE-EXAMPLE; ya29.synthetic")):
            with self.assertRaises(RuntimeError) as raised:
                access_token(Mock())
        self.assertNotIn("SENSITIVE-EXAMPLE", str(raised.exception))
        self.assertNotIn("ya29", str(raised.exception))

    def test_personal_user_credentials_are_not_accepted_as_service_account_json(self):
        with patch.dict("os.environ", {"GOOGLE_SERVICE_ACCOUNT_JSON":'{"type":"authorized_user"}'}), \
                patch("cloud_auth.service_account.Credentials.from_service_account_info") as load:
            with self.assertRaises(RuntimeError):
                access_token(Mock())
        load.assert_not_called()

    def test_two_configured_credential_sources_require_an_explicit_choice(self):
        with patch.dict("os.environ", {"GOOGLE_SERVICE_ACCOUNT_JSON":"{}", "GOOGLE_APPLICATION_CREDENTIALS":"example.json"}):
            with self.assertRaisesRegex(RuntimeError, "Choose one"):
                access_token(Mock())

    def test_auth_transport_has_a_bounded_timeout(self):
        with requests.Session() as session, patch("cloud_auth.AuthRequest.__call__") as send:
            BoundedAuthRequest(session=session)("https://oauth2.googleapis.com/token", timeout=300)
        self.assertEqual(send.call_args.kwargs["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
