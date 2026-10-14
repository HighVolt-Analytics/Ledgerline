import importlib.util
import os
from pathlib import Path
import smtplib
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "send-deployment-notification.py"
SPEC = importlib.util.spec_from_file_location("ledgerline_notification", SCRIPT)
NOTIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NOTIFIER)


class FakeSMTP:
    sent = []

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        pass

    def starttls(self, **_kwargs):
        pass

    def login(self, username, password):
        assert username == "smtp-user-sentinel"
        assert password == "smtp-password-sentinel"

    def send_message(self, message):
        self.sent.append(message.get_content())


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "SMTP_HOST": "mail.example.test",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "smtp-user-sentinel",
            "SMTP_PASSWORD": "smtp-password-sentinel",
            "MAIL_FROM": "deploy@example.test",
            "MAIL_TO": "ops@example.test",
            "RELEASE_COMMIT": "a" * 40,
            "GITHUB_REPOSITORY": "HighVolt-Analytics/Ledgerline",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_ACTOR": "operator",
            "DEPLOY_EVENT": "workflow_dispatch",
            "BUILD_RESULT": "success",
            "DEPLOY_RESULT": "success",
            "ROLLBACK_RESULT": "",
            "GH_TOKEN": "github-token-sentinel",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_success_message_contains_release_and_health_without_credentials(self):
        FakeSMTP.sent.clear()
        with patch.object(NOTIFIER, "github_run_details", return_value=("none", "No", "Not required", "2026-10-14T00:00:00Z")), \
             patch.object(NOTIFIER, "live_health", return_value=(True, f"Commit: {'a' * 40}", "HTTPS homepage: healthy")), \
             patch.object(NOTIFIER.smtplib, "SMTP", FakeSMTP), \
             patch.object(NOTIFIER.time, "sleep"):
            NOTIFIER.main()
        message = FakeSMTP.sent[-1]
        self.assertIn("Final result: Success", message)
        self.assertIn("quantumledgerline.com", message)
        self.assertIn("/actions/runs/12345", message)
        self.assertIn("2026-10-14T00:00:00Z", message)
        self.assertNotIn("smtp-password-sentinel", message)
        self.assertNotIn("github-token-sentinel", message)

    def test_failure_retries_three_times_without_printing_secret_values(self):
        attempts = []

        class FailingSMTP(FakeSMTP):
            def send_message(self, _message):
                attempts.append(1)
                raise smtplib.SMTPException("provider error with password sentinel")

        with patch.object(NOTIFIER, "github_run_details", return_value=("Overlay release", "Yes", "Failed", "2026-10-14T00:00:00Z")), \
             patch.object(NOTIFIER, "live_health", return_value=(False, "unavailable", "HTTPS homepage/marker: unavailable")), \
             patch.object(NOTIFIER.smtplib, "SMTP", FailingSMTP), \
             patch.object(NOTIFIER.time, "sleep"):
            with self.assertRaises(smtplib.SMTPException):
                NOTIFIER.main()
        self.assertEqual(len(attempts), 3)


if __name__ == "__main__":
    unittest.main()
