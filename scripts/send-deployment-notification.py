import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required notification setting: {name}")
    return value


def github_run_details():
    repository = required("GITHUB_REPOSITORY")
    run_id = required("GITHUB_RUN_ID")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {required('GH_TOKEN')}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        jobs = json.load(response).get("jobs", [])

    run_request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {required('GH_TOKEN')}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(run_request, timeout=15) as response:
        created_at = json.load(response).get("run_started_at") or "unknown"

    failed_stage = "none"
    rollback_attempted = "No"
    rollback_result = "Not required"
    for job in jobs:
        if job.get("name") != "Deploy and verify approved production release":
            continue
        failed = next(
            (step for step in job.get("steps", []) if step.get("conclusion") == "failure"),
            None,
        )
        if failed:
            failed_stage = failed.get("name", "unknown")
        rollback = next(
            (step for step in job.get("steps", []) if step.get("name") == "Restore pre-deployment snapshot after a release failure"),
            None,
        )
        if rollback and rollback.get("conclusion") != "skipped":
            rollback_attempted = "Yes"
            rollback_result = "Verified" if rollback.get("conclusion") == "success" else "Failed"
    return failed_stage, rollback_attempted, rollback_result, created_at


def live_health():
    result = []
    marker = "unavailable"
    ok = False
    try:
        request = urllib.request.Request("https://quantumledgerline.com/deploy-info.txt")
        with urllib.request.urlopen(request, timeout=12) as response:
            marker = response.read(4096).decode("utf-8", errors="replace").strip()
        with urllib.request.urlopen("https://quantumledgerline.com/", timeout=12) as response:
            ok = response.status == 200
        result.append(f"HTTPS homepage: {'healthy' if ok else 'unhealthy'}")
        result.append(f"Live marker: {marker}")
    except (OSError, urllib.error.URLError, TimeoutError):
        result.append("HTTPS homepage/marker: unavailable")
    return ok, marker, "; ".join(result)


def main():
    smtp_host = required("SMTP_HOST")
    smtp_port = int(required("SMTP_PORT"))
    username = required("SMTP_USERNAME")
    password = required("SMTP_PASSWORD")
    sender = required("MAIL_FROM")
    recipients = required("MAIL_TO")
    release = required("RELEASE_COMMIT")
    repository = required("GITHUB_REPOSITORY")
    run_url = f"{os.environ['GITHUB_SERVER_URL']}/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    trigger = f"{required('DEPLOY_EVENT')} by {required('GITHUB_ACTOR')}"
    build_result = os.environ.get("BUILD_RESULT", "unknown")
    deploy_result = os.environ.get("DEPLOY_RESULT", "unknown")
    rollback_job_output = os.environ.get("ROLLBACK_RESULT", "")
    failed_stage, rollback_attempted, rollback_result, started_at = github_run_details()
    if rollback_job_output == "verified":
        rollback_result = "Verified"
    healthy, marker, health_summary = live_health()
    marker_matches_release = f"Commit: {release}" in marker
    success = deploy_result == "success" and healthy and marker_matches_release
    subject = (
        f"Ledgerline production {'SUCCESS' if success else 'FAILURE'} — {release[:12]}"
    )
    body = "\n".join(
        [
            "Ledgerline production deployment outcome",
            "Domain: quantumledgerline.com",
            f"Repository and branch: {repository} / main",
            f"Commit: {release}",
            f"Initiator or trigger: {trigger}",
            f"GitHub Actions run: {run_url}",
            f"Deployment timestamp (UTC): {started_at}",
            f"Final result: {'Success' if success else 'Failure'} (build={build_result}, deploy={deploy_result})",
            f"Health checks: {'deployment routes verified by deploy workflow' if deploy_result == 'success' else 'deployment checks did not all pass'}; {health_summary}",
            f"Failure stage: {failed_stage if deploy_result != 'success' else ('none' if success else 'Final live site verification')}",
            f"Rollback attempted: {rollback_attempted}",
            f"Rollback result: {rollback_result}",
            f"Final live marker: {marker}",
            f"Final live homepage health: {'healthy' if healthy else 'unhealthy'}",
        ]
    )
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipients
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    last_error = None
    for attempt in range(3):
        try:
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=20) as client:
                    client.login(username, password)
                    client.send_message(message)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as client:
                    client.ehlo()
                    client.starttls(context=context)
                    client.ehlo()
                    client.login(username, password)
                    client.send_message(message)
            break
        except (OSError, smtplib.SMTPException) as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    else:
        raise last_error
    print("Email notification sent.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Keep exception details limited to type; SMTP/network errors can contain endpoint data.
        print(f"Email notification failed ({type(error).__name__}).", file=sys.stderr)
        sys.exit(1)
