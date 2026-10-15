import importlib.util
import io
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import unittest
from unittest.mock import patch


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


def http_error(status, body):
    return urllib.error.HTTPError(
        "https://service.example.invalid", status, "failure", {}, io.BytesIO(body.encode())
    )


class GraphNotificationDiagnosticTests(unittest.TestCase):
    def test_oidc_assertion_retrieval_failure_is_classified_and_redacted(self):
        sensitive = "{" + '"error":"forbidden","details":"support@highvolt.tech JWT_SECRET_SENTINEL"' + "}"
        with patch("urllib.request.urlopen", side_effect=http_error(403, sensitive)):
            with self.assertRaises(GRAPH.MailGraphError) as raised:
                GRAPH._json_request(None, 200, "oidc_assertion_retrieval")
        self.assertEqual(raised.exception.stage, "oidc_assertion_retrieval")
        self.assertEqual(raised.exception.category, "oidc_assertion_retrieval_failed")
        self.assertNotIn("support@highvolt.tech", str(raised.exception))
        self.assertNotIn("JWT_SECRET_SENTINEL", str(raised.exception))

    def test_federated_credential_mismatch_is_distinguished(self):
        body = '{"error":"invalid_client","error_description":"AADSTS700213: federated identity credential subject mismatch"}'
        with patch("urllib.request.urlopen", side_effect=http_error(400, body)):
            with self.assertRaises(GRAPH.MailGraphError) as raised:
                GRAPH._json_request(None, 200, "entra_token_exchange")
        self.assertEqual(raised.exception.stage, "entra_token_exchange")
        self.assertEqual(raised.exception.category, "federated_credential_mismatch")
        self.assertNotIn("AADSTS700213", str(raised.exception))

    def test_invalid_audience_or_issuer_is_distinguished(self):
        body = '{"error":"invalid_client","error_description":"The audience is invalid for this issuer"}'
        with patch("urllib.request.urlopen", side_effect=http_error(400, body)):
            with self.assertRaises(GRAPH.MailGraphError) as raised:
                GRAPH._json_request(None, 200, "entra_token_exchange")
        self.assertEqual(raised.exception.category, "invalid_audience_or_issuer")

    def test_other_token_exchange_rejection_uses_generic_allowlisted_category(self):
        with patch("urllib.request.urlopen", side_effect=http_error(400, '{"error":"invalid_client"}')):
            with self.assertRaises(GRAPH.MailGraphError) as raised:
                GRAPH._json_request(None, 200, "entra_token_exchange")
        self.assertEqual(raised.exception.category, "token_exchange_rejected")

    def test_graph_permission_denial_is_distinguished_and_redacted(self):
        body = '{"error":{"code":"Authorization_RequestDenied","message":"secret@highvolt.tech ACCESS_TOKEN_SENTINEL"}}'
        with patch("urllib.request.urlopen", side_effect=http_error(403, body)):
            with self.assertRaises(GRAPH.MailGraphError) as raised:
                GRAPH._json_request(None, 202, "graph_response_handling")
        self.assertEqual(raised.exception.category, "graph_permission_denied")
        self.assertNotIn("secret@highvolt.tech", str(raised.exception))
        self.assertNotIn("ACCESS_TOKEN_SENTINEL", str(raised.exception))

    def test_graph_validation_failure_is_distinguished(self):
        with patch("urllib.request.urlopen", side_effect=http_error(400, '{"error":{"code":"BadRequest"}}')):
            with self.assertRaises(GRAPH.MailGraphError) as raised:
                GRAPH._json_request(None, 202, "graph_response_handling")
        self.assertEqual(raised.exception.category, "graph_request_validation_failed")

    def test_network_failure_is_classified_without_exception_text(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("sensitive@highvolt.tech TOKEN_SENTINEL"),
        ):
            with self.assertRaises(GRAPH.MailGraphError) as raised:
                GRAPH._json_request(None, 202, "graph_sendmail")
        self.assertEqual(raised.exception.stage, "graph_sendmail")
        self.assertEqual(raised.exception.category, "network_or_timeout")
        self.assertNotIn("sensitive@highvolt.tech", str(raised.exception))
        self.assertNotIn("TOKEN_SENTINEL", str(raised.exception))

    def test_graph_response_handling_failure_is_separate_from_send_request(self):
        with patch("urllib.request.urlopen", side_effect=http_error(503, "upstream error")):
            with self.assertRaises(GRAPH.MailGraphError) as raised:
                GRAPH._json_request(None, 202, "graph_response_handling")
        self.assertEqual(raised.exception.stage, "graph_response_handling")
        self.assertEqual(raised.exception.category, "network_or_timeout")

    def test_oidc_token_exchange_and_graph_sendmail_targets_are_correct(self):
        with patch.dict(os.environ, {
            "MAIL_TENANT_ID": "tenant-sentinel",
            "MAIL_CLIENT_ID": "client-sentinel",
            "MAIL_FROM": "support@example.test",
            "MAIL_TO": "alerts@example.test",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://actions.example.test/oidc?foo=bar",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "github-request-token-sentinel",
        }):
            responses = [
                FakeResponse(200, json.dumps({"value": "oidc-assertion-sentinel"}).encode()),
                FakeResponse(200, json.dumps({"access_token": "graph-access-token-sentinel"}).encode()),
                FakeResponse(202),
            ]
            requests = []

            def respond(request, timeout):
                requests.append(request)
                self.assertEqual(timeout, 20)
                return responses.pop(0)

            with patch("urllib.request.urlopen", side_effect=respond):
                GRAPH.send_mail("subject sentinel", "body sentinel")

        oidc_query = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[0].full_url).query)
        self.assertEqual(oidc_query["audience"], ["api://AzureADTokenExchange"])
        token_form = urllib.parse.parse_qs(requests[1].data.decode())
        self.assertEqual(token_form["scope"], ["https://graph.microsoft.com/.default"])
        self.assertEqual(token_form["grant_type"], ["client_credentials"])
        self.assertTrue(requests[2].full_url.startswith(
            "https://graph.microsoft.com/v1.0/users/support%40example.test/sendMail"
        ))
        self.assertEqual(requests[2].get_method(), "POST")


if __name__ == "__main__":
    unittest.main()
