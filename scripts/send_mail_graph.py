"""Send mail through Microsoft Graph using a GitHub Actions OIDC identity."""

import json
import http.client
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


ERROR_CATEGORIES = {
    "federated_credential_mismatch",
    "invalid_audience_or_issuer",
    "token_exchange_rejected",
    "oidc_assertion_retrieval_failed",
    "graph_permission_denied",
    "graph_request_validation_failed",
    "network_or_timeout",
    "invalid_service_response",
    "unexpected_http_status",
    "missing_configuration",
    "notification_failed",
    "unexpected_failure",
}


class MailGraphError(Exception):
    """Safe error containing only an allowlisted stage and category."""

    def __init__(self, stage, category):
        self.stage = stage if stage in {
            "configuration",
            "oidc_assertion_retrieval",
            "entra_token_exchange",
            "graph_sendmail",
            "graph_response_handling",
            "smoke_test",
        } else "smoke_test"
        self.category = category if category in ERROR_CATEGORIES else "unexpected_failure"
        super().__init__(f"stage={self.stage} category={self.category}")


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise MailGraphError("configuration", "missing_configuration")
    return value


def _error_category(stage, status, payload):
    """Classify a service failure without returning or logging response text."""
    try:
        document = json.loads(payload) if payload else {}
    except (TypeError, ValueError):
        document = {}

    error = document.get("error", {}) if isinstance(document, dict) else {}
    if isinstance(error, dict):
        details = " ".join(
            str(error.get(key, ""))
            for key in ("code", "message", "error_description")
        )
        details += " " + " ".join(str(item) for item in error.get("innerError", {}).values()) \
            if isinstance(error.get("innerError"), dict) else ""
    else:
        details = str(error)
        if isinstance(document, dict):
            details += " " + str(document.get("error_description", ""))
    lowered = details.lower()

    if stage == "entra_token_exchange":
        if any(code in lowered for code in ("aadsts70021", "aadsts700211", "aadsts700213")) \
                or ("federated" in lowered and "credential" in lowered):
            return "federated_credential_mismatch"
        if ("audience" in lowered and ("invalid" in lowered or "match" in lowered)) \
                or ("issuer" in lowered and ("invalid" in lowered or "match" in lowered)):
            return "invalid_audience_or_issuer"
        return "token_exchange_rejected"

    if stage == "oidc_assertion_retrieval":
        if status in (401, 403):
            return "oidc_assertion_retrieval_failed"
        return "oidc_assertion_retrieval_failed"

    if stage == "graph_response_handling":
        if status in (401, 403):
            return "graph_permission_denied"
        if status in (400, 404, 422):
            return "graph_request_validation_failed"
        if status == 429 or (status is not None and status >= 500):
            return "network_or_timeout"
    return "unexpected_http_status"


def _json_request(request, expected_status, stage):
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            payload = response.read()
    except urllib.error.HTTPError as error:
        try:
            payload = error.read()
        except Exception:
            payload = b""
        raise MailGraphError(stage, _error_category(stage, error.code, payload)) from None
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        TimeoutError,
        socket.timeout,
        ConnectionError,
        OSError,
    ):
        raise MailGraphError(stage, "network_or_timeout") from None
    except Exception:
        raise MailGraphError(stage, "unexpected_failure") from None

    if status != expected_status:
        raise MailGraphError(stage, _error_category(stage, status, payload))
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except (TypeError, ValueError):
        raise MailGraphError(stage, "invalid_service_response") from None


def acquire_graph_token():
    tenant = urllib.parse.quote(required("MAIL_TENANT_ID"), safe="")
    client_id = required("MAIL_CLIENT_ID")
    oidc_url = required("ACTIONS_ID_TOKEN_REQUEST_URL")
    oidc_request_token = required("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    parts = urllib.parse.urlsplit(oidc_url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append(("audience", "api://AzureADTokenExchange"))
    oidc_url = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )
    oidc_request = urllib.request.Request(
        oidc_url,
        headers={"Authorization": f"Bearer {oidc_request_token}"},
    )
    oidc_payload = _json_request(oidc_request, 200, "oidc_assertion_retrieval")
    assertion = oidc_payload.get("value")
    if not isinstance(assertion, str) or not assertion:
        raise MailGraphError("oidc_assertion_retrieval", "invalid_service_response")

    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    form = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
        }
    ).encode("ascii")
    token_request = urllib.request.Request(
        token_url,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    token_payload = _json_request(token_request, 200, "entra_token_exchange")
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise MailGraphError("entra_token_exchange", "invalid_service_response")
    return access_token


def send_mail(subject, body, sender=None, recipients=None):
    sender = (sender or required("MAIL_FROM")).strip()
    recipients = recipients or required("MAIL_TO")
    addresses = [item.strip() for item in recipients.replace(";", ",").split(",") if item.strip()]
    if not sender or not addresses:
        raise MailGraphError("configuration", "missing_configuration")

    token = acquire_graph_token()
    sender_path = urllib.parse.quote(sender, safe="")
    graph_url = f"https://graph.microsoft.com/v1.0/users/{sender_path}/sendMail"
    payload = json.dumps(
        {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [
                    {"emailAddress": {"address": address}} for address in addresses
                ],
            },
            "saveToSentItems": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        graph_url,
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(3):
        try:
            _json_request(request, 202, "graph_response_handling")
            return
        except MailGraphError as error:
            if error.category not in {"network_or_timeout"} or attempt == 2:
                raise
            time.sleep(2 ** attempt)
