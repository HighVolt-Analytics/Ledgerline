"""Send mail through Microsoft Graph using a GitHub Actions OIDC identity."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


class MailGraphError(Exception):
    """Safe error that never includes request bodies, tokens, or message addresses."""


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise MailGraphError(f"Missing required setting: {name}")
    return value


def _json_request(request, expected_status):
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != expected_status:
                raise MailGraphError("UnexpectedServiceResponse")
            payload = response.read()
    except MailGraphError:
        raise
    except Exception as error:
        raise MailGraphError(type(error).__name__) from None
    try:
        return json.loads(payload) if payload else {}
    except (TypeError, ValueError):
        raise MailGraphError("InvalidServiceResponse") from None


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
    oidc_payload = _json_request(oidc_request, 200)
    assertion = oidc_payload.get("value")
    if not isinstance(assertion, str) or not assertion:
        raise MailGraphError("MissingOIDCToken")

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
    token_payload = _json_request(token_request, 200)
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise MailGraphError("MissingAccessToken")
    return access_token


def send_mail(subject, body, sender=None, recipients=None):
    sender = (sender or required("MAIL_FROM")).strip()
    recipients = recipients or required("MAIL_TO")
    addresses = [item.strip() for item in recipients.replace(";", ",").split(",") if item.strip()]
    if not sender or not addresses:
        raise MailGraphError("MissingMailAddress")

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
            _json_request(request, 202)
            return
        except MailGraphError as error:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
