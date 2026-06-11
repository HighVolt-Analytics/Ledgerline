"""Send email via Microsoft Graph (application permission Mail.Send)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.services.graph_client import graph_credentials_configured, graph_request
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class GraphMailResult:
    sent: bool
    error: str | None = None


def graph_mail_send_configured() -> bool:
    settings = get_settings()
    return graph_credentials_configured() and bool(settings.graph_mailbox.strip())


def send_graph_mail(
    *,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
    from_mailbox: str | None = None,
) -> GraphMailResult:
    """Send mail as the configured GRAPH_MAILBOX user."""
    if not graph_mail_send_configured():
        return GraphMailResult(
            sent=False,
            error="Graph mail is not configured (set AZURE_* and GRAPH_MAILBOX).",
        )

    settings = get_settings()
    sender = (from_mailbox or settings.graph_mailbox).strip()
    if not sender:
        return GraphMailResult(sent=False, error="GRAPH_MAILBOX is empty.")

    payload: dict[str, Any] = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
        "saveToSentItems": True,
    }

    try:
        graph_request(
            "POST",
            f"/users/{sender}/sendMail",
            json_body=payload,
        )
        return GraphMailResult(sent=True)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        if exc.response.status_code == 403:
            message = (
                "Microsoft Graph denied send (403). Add Mail.Send application permission "
                f"and grant admin consent in Entra ID for {sender}."
            )
        else:
            message = f"Graph sendMail failed ({exc.response.status_code})."
        logger.warning(
            "graph_send_mail_failed",
            to=to_email,
            from_mailbox=sender,
            status=exc.response.status_code,
            error=detail,
        )
        return GraphMailResult(sent=False, error=message)
    except Exception as exc:
        logger.warning(
            "graph_send_mail_failed",
            to=to_email,
            from_mailbox=sender,
            error=str(exc),
        )
        return GraphMailResult(sent=False, error=str(exc))
