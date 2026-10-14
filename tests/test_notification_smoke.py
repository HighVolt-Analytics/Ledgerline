import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "send-notification-smoke.py"
SPEC = importlib.util.spec_from_file_location("notification_smoke", SCRIPT)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class NotificationSmokeTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "MAIL_TENANT_ID": "tenant-id-sentinel",
            "MAIL_CLIENT_ID": "client-id-sentinel",
            "MAIL_FROM": "support@example.test",
            "MAIL_TO": "alerts@example.test",
            "SMOKE_OUTCOME": "both",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_both_messages_are_clearly_simulated_and_no_deployment_occurs(self):
        sent = []
        with patch.object(SMOKE, "send_mail", side_effect=lambda *args: sent.append(args)), \
             patch("builtins.print") as output:
            SMOKE.main()
        self.assertEqual(len(sent), 2)
        self.assertIn("SIMULATED NOTIFICATION — SUCCESS", sent[0][0])
        self.assertIn("SIMULATED NOTIFICATION — FAILURE", sent[1][0])
        self.assertIn("No production deployment was run", sent[0][1])
        self.assertEqual(sent[0][2:], ("support@example.test", "alerts@example.test"))
        logged = str(output.call_args_list)
        self.assertNotIn("support@example.test", logged)
        self.assertNotIn("alerts@example.test", logged)
        self.assertNotIn("client-id-sentinel", logged)

    def test_missing_identity_settings_fail_before_graph_call(self):
        with patch.dict(os.environ, {"MAIL_CLIENT_ID": ""}), \
             patch.object(SMOKE, "send_mail") as send_mail, \
             patch("builtins.print") as output:
            with self.assertRaisesRegex(SMOKE.MailGraphError, "MAIL_CLIENT_ID"):
                SMOKE.main()
        send_mail.assert_not_called()
        self.assertNotIn("support@example.test", str(output.call_args_list))

    def test_send_failure_logs_only_exception_type(self):
        with patch.object(SMOKE, "send_mail", side_effect=SMOKE.MailGraphError("HTTPError")), \
             patch("builtins.print") as output:
            with self.assertRaisesRegex(SMOKE.MailGraphError, "MailGraphError"):
                SMOKE.main()
        self.assertNotIn("support@example.test", str(output.call_args_list))
        self.assertNotIn("alerts@example.test", str(output.call_args_list))


if __name__ == "__main__":
    unittest.main()
