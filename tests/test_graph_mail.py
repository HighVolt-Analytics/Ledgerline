import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse


SCRIPT = Path(__file__).parents[1] / "scripts" / "send_mail_graph.py"
SPEC = importlib.util.spec_from_file_location("send_mail_graph", SCRIPT)
GRAPH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAPH)


class FakeResponse:
    def __init__(self, status, payload=b""):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class GraphMailTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "MAIL_TENANT_ID": "tenant-id-sentinel",
            "MAIL_CLIENT_ID": "client-id-sentinel",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.actions.example/oidc?existing=value",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "github-request-token-sentinel",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_oidc_exchange_and_graph_send_use_scoped_app_identity(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            if len(requests) == 1:
                return FakeResponse(200, b'{"value":"oidc-assertion-sentinel"}')
            if len(requests) == 2:
                return FakeResponse(200, b'{"access_token":"graph-token-sentinel"}')
            return FakeResponse(202)

        with patch.object(GRAPH.urllib.request, "urlopen", side_effect=fake_urlopen):
            GRAPH.send_mail(
                "Test subject", "Test body", "support@example.test", "ops@example.test"
            )

        self.assertEqual(len(requests), 3)
        oidc_request, _ = requests[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(oidc_request.full_url).query)
        self.assertEqual(query["existing"], ["value"])
        self.assertEqual(query["audience"], ["api://AzureADTokenExchange"])
        self.assertEqual(oidc_request.get_header("Authorization"), "Bearer github-request-token-sentinel")

        token_request, _ = requests[1]
        form = urllib.parse.parse_qs(token_request.data.decode("ascii"))
        self.assertEqual(form["grant_type"], ["client_credentials"])
        self.assertEqual(form["client_id"], ["client-id-sentinel"])
        self.assertEqual(form["client_assertion"], ["oidc-assertion-sentinel"])
        self.assertEqual(form["scope"], ["https://graph.microsoft.com/.default"])

        graph_request, _ = requests[2]
        self.assertTrue(graph_request.full_url.endswith("/users/support%40example.test/sendMail"))
        self.assertEqual(graph_request.get_header("Authorization"), "Bearer graph-token-sentinel")
        body = json.loads(graph_request.data)
        self.assertEqual(body["message"]["toRecipients"][0]["emailAddress"]["address"], "ops@example.test")
        self.assertFalse(body["saveToSentItems"])

    def test_provider_error_is_redacted(self):
        provider_error = urllib.error.HTTPError(
            "https://login.example.test", 401, "bad", {}, None
        )
        with patch.object(GRAPH.urllib.request, "urlopen", side_effect=provider_error):
            with self.assertRaises(GRAPH.MailGraphError) as error:
                GRAPH.acquire_graph_token()
        self.assertEqual(error.exception.stage, "oidc_assertion_retrieval")
        self.assertEqual(error.exception.category, "oidc_assertion_retrieval_failed")
        self.assertNotIn("github-request-token-sentinel", str(error.exception))


if __name__ == "__main__":
    unittest.main()
