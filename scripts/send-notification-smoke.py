"""Send simulated deployment notices through Microsoft Graph; no deploy code runs."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from send_mail_graph import MailGraphError, required, send_mail


def main():
    required("MAIL_TENANT_ID")
    required("MAIL_CLIENT_ID")
    sender = required("MAIL_FROM")
    recipients = required("MAIL_TO")
    outcome = os.environ.get("SMOKE_OUTCOME", "both")
    if outcome not in {"success", "failure", "both"}:
        raise MailGraphError("smoke_test", "unexpected_failure")

    outcomes = ("success", "failure") if outcome == "both" else (outcome,)
    failures = False
    for simulated in outcomes:
        subject = f"SIMULATED NOTIFICATION — {simulated.upper()} (NO DEPLOYMENT)"
        body = "\n".join(
            [
                "This is a simulated Ledgerline deployment notification smoke test.",
                f"Simulated outcome: {simulated.upper()}.",
                "No production deployment was run and no website files were changed.",
            ]
        )
        try:
            send_mail(subject, body, sender, recipients)
        except MailGraphError as error:
            print(
                f"Notification failure: stage={error.stage} category={error.category}",
                file=sys.stderr,
            )
            failures = True
        except Exception:
            print(
                "Notification failure: stage=smoke_test category=unexpected_failure",
                file=sys.stderr,
            )
            failures = True
        else:
            print(f"Simulated {simulated} notification accepted by Microsoft Graph.")
    if failures:
        raise MailGraphError("smoke_test", "notification_failed")


if __name__ == "__main__":
    try:
        main()
    except MailGraphError as error:
        print(
            f"Notification smoke test failed: stage={error.stage} category={error.category}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception:
        print(
            "Notification smoke test failed: stage=smoke_test category=unexpected_failure",
            file=sys.stderr,
        )
        sys.exit(1)
