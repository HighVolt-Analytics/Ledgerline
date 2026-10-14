import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "send-deployment-notification.py"
SPEC = importlib.util.spec_from_file_location("ledgerline_notification", SCRIPT)
NOTIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NOTIFIER)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "MAIL_TENANT_ID": "tenant-id-sentinel",
            "MAIL_CLIENT_ID": "client-id-sentinel",
            "MAIL_FROM": "support@example.test",
            "MAIL_TO": "alerts@example.test",
            "RELEASE_COMMIT": "a" * 40,
            "GITHUB_REPOSITORY": "HighVolt-Analytics/Ledgerline",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_ACTOR": "operator",
            "DEPLOY_EVENT": "workflow_dispatch",
            "BUILD_RESULT": "success",
            "DEPLOY_RESULT": "success",
            "ROLLBACK_RESULT": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_success_message_keeps_release_health_and_rollback_context(self):
        sent = []
        with patch.object(NOTIFIER, "github_run_details", return_value=("none", "No", "Not required", "2026-10-14T00:00:00Z")), \
             patch.object(NOTIFIER, "live_health", return_value=(True, f"Commit: {'a' * 40}", "HTTPS homepage: healthy")), \
             patch.object(NOTIFIER, "send_mail", side_effect=lambda *args: sent.append(args)):
            NOTIFIER.main()
        subject, body, sender, recipients = sent[0]
        self.assertIn("SUCCESS", subject)
        self.assertIn("Final result: Success", body)
        self.assertIn("quantumledgerline.com", body)
        self.assertIn("/actions/runs/12345", body)
        self.assertIn("Rollback result: Not required", body)
        self.assertEqual((sender, recipients), ("support@example.test", "alerts@example.test"))

    def test_failure_message_preserves_failed_stage_and_rollback_status(self):
        sent = []
        with patch.dict(os.environ, {"DEPLOY_RESULT": "failure"}), \
             patch.object(NOTIFIER, "github_run_details", return_value=("Overlay release", "Yes", "Failed", "2026-10-14T00:00:00Z")), \
             patch.object(NOTIFIER, "live_health", return_value=(False, "unavailable", "HTTPS homepage/marker: unavailable")), \
             patch.object(NOTIFIER, "send_mail", side_effect=lambda *args: sent.append(args)):
            NOTIFIER.main()
        subject, body, _sender, _recipients = sent[0]
        self.assertIn("FAILURE", subject)
        self.assertIn("Failure stage: Overlay release", body)
        self.assertIn("Rollback attempted: Yes", body)
        self.assertIn("Rollback result: Failed", body)


if __name__ == "__main__":
    unittest.main()
