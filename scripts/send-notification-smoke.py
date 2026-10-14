"""Send simulated deployment notifications without invoking deployment code."""

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage


MAIL_SETTINGS = (
    "MAIL_HOST",
    "MAIL_PORT",
    "MAIL_USERNAME",
    "MAIL_PASSWORD",
    "MAIL_FROM",
    "MAIL_TO",
)


def load_settings():
    values = {name: os.environ.get(name, "").strip() for name in MAIL_SETTINGS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError("Missing required notification settings: " + ", ".join(missing))
    try:
        values["MAIL_PORT"] = int(values["MAIL_PORT"])
    except ValueError as error:
        raise ValueError("MAIL_PORT must be an integer") from error
    if not 1 <= values["MAIL_PORT"] <= 65535:
        raise ValueError("MAIL_PORT must be between 1 and 65535")
    outcome = os.environ.get("SMOKE_OUTCOME", "both")
    if outcome not in {"success", "failure", "both"}:
        raise ValueError("SMOKE_OUTCOME must be success, failure, or both")
    return values, outcome


def create_message(sender, recipients, outcome):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipients
    message["Subject"] = f"SIMULATED NOTIFICATION — {outcome.upper()} (NO DEPLOYMENT)"
    message.set_content(
        "This is a simulated Ledgerline deployment notification smoke test.\n"
        f"Simulated outcome: {outcome.upper()}.\n"
        "No production deployment was run and no website files were changed.\n"
    )
    return message


def send_one(settings, outcome):
    context = ssl.create_default_context()
    message = create_message(settings["MAIL_FROM"], settings["MAIL_TO"], outcome)
    if settings["MAIL_PORT"] == 465:
        with smtplib.SMTP_SSL(
            settings["MAIL_HOST"], settings["MAIL_PORT"], context=context, timeout=20
        ) as client:
            client.login(settings["MAIL_USERNAME"], settings["MAIL_PASSWORD"])
            client.send_message(message)
    else:
        with smtplib.SMTP(settings["MAIL_HOST"], settings["MAIL_PORT"], timeout=20) as client:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
            client.login(settings["MAIL_USERNAME"], settings["MAIL_PASSWORD"])
            client.send_message(message)


def main():
    settings, requested = load_settings()
    outcomes = ("success", "failure") if requested == "both" else (requested,)
    failures = []
    for outcome in outcomes:
        try:
            send_one(settings, outcome)
        except Exception as error:  # Avoid logging provider diagnostics or message headers.
            failures.append(type(error).__name__)
        else:
            print(f"Simulated {outcome} notification sent.")
    if failures:
        raise RuntimeError("One or more simulated notifications failed: " + ", ".join(failures))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Notification smoke test failed ({type(error).__name__}).", file=sys.stderr)
        sys.exit(1)
