import importlib.util
import os
from pathlib import Path
import smtplib
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "send-notification-smoke.py"
SPEC = importlib.util.spec_from_file_location("notification_smoke", SCRIPT)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


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
        assert username == "username-sentinel"
        assert password == "password-sentinel"

    def send_message(self, message):
        self.sent.append(message)


class FailingSMTP(FakeSMTP):
    attempts = 0

    def send_message(self, _message):
        type(self).attempts += 1
        raise smtplib.SMTPException("sensitive provider detail password-sentinel")


class NotificationSmokeTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "MAIL_HOST": "mail.example.test",
            "MAIL_PORT": "587",
            "MAIL_USERNAME": "username-sentinel",
            "MAIL_PASSWORD": "password-sentinel",
            "MAIL_FROM": "sender@example.test",
            "MAIL_TO": "recipient@example.test",
            "SMOKE_OUTCOME": "both",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        FakeSMTP.sent.clear()

    def test_both_simulated_outcomes_are_sent_without_logging_headers_or_password(self):
        with patch.object(SMOKE.smtplib, "SMTP", FakeSMTP), patch("builtins.print") as output:
            SMOKE.main()
        self.assertEqual(len(FakeSMTP.sent), 2)
        for message, outcome in zip(FakeSMTP.sent, ("SUCCESS", "FAILURE")):
            self.assertIn(f"SIMULATED NOTIFICATION — {outcome}", message["Subject"])
            self.assertIn("No production deployment was run", message.get_content())
            self.assertNotIn("password-sentinel", message.as_string())
        printed = " ".join(str(call) for call in output.call_args_list)
        self.assertNotIn("password-sentinel", printed)
        self.assertNotIn("recipient@example.test", printed)

    def test_missing_secret_fails_before_smtp_connection(self):
        with patch.dict(os.environ, {"MAIL_PASSWORD": ""}), \
             patch.object(SMOKE.smtplib, "SMTP") as smtp, \
             patch("builtins.print") as output:
            with self.assertRaisesRegex(ValueError, "MAIL_PASSWORD"):
                SMOKE.main()
        smtp.assert_not_called()
        self.assertNotIn("password-sentinel", str(output.call_args_list))

    def test_failure_details_are_redacted_and_both_outcomes_are_attempted(self):
        FailingSMTP.attempts = 0
        with patch.object(SMOKE.smtplib, "SMTP", FailingSMTP), patch("builtins.print") as output:
            with self.assertRaisesRegex(RuntimeError, "SMTPException") as error:
                SMOKE.main()
        self.assertEqual(FailingSMTP.attempts, 2)
        self.assertNotIn("password-sentinel", str(error.exception))
        self.assertNotIn("recipient@example.test", str(output.call_args_list))


if __name__ == "__main__":
    unittest.main()
