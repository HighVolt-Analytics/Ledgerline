"""Patch AKS production ConfigMap with login OAuth redirect URIs.

Production was falling back to localhost defaults for MICROSOFT_OAUTH_REDIRECT_URI
and GOOGLE_OAUTH_REDIRECT_URI, which causes AADSTS50011 on Microsoft sign-in.

Usage (from backend/, kubectl context = highvolt-aks):

    python scripts/patch_production_oauth_env.py
    python scripts/patch_production_oauth_env.py --restart

Does not print secret values. Client id/secret continue to resolve from
AZURE_CLIENT_ID / AZURE_CLIENT_SECRET (or dedicated MICROSOFT_* keys if present).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

_PROD_NS = "quantum-ledgerlink-prod"
_CONFIGMAP = "ledgerlink-config"
_SECRET = "app-secrets"
_PROD_BASE = "https://ledgerlink.highvolt.tech"

# Confidential client + backend callback (not SPA localhost).
# SaaS multi-tenant login uses /common (requires Multitenant Entra app).
# Never copy AZURE_TENANT_ID into MICROSOFT_OAUTH_AUTHORITY_TENANT — that GUID
# is for Graph/mailbox only.
_CONFIG_VALUES_BASE = {
    "FRONTEND_URL": _PROD_BASE,
    "MICROSOFT_OAUTH_REDIRECT_URI": f"{_PROD_BASE}/api/auth/oauth/microsoft/callback",
    "MICROSOFT_OAUTH_PUBLIC_CLIENT": "false",
    "GOOGLE_OAUTH_REDIRECT_URI": f"{_PROD_BASE}/api/auth/oauth/google/callback",
    "MICROSOFT_OAUTH_AUTHORITY_TENANT": "common",
}


def _explicit_login_authority_from_secrets() -> str | None:
    """Optional override from app-secrets MICROSOFT_OAUTH_AUTHORITY_TENANT only."""
    import base64

    proc = subprocess.run(
        ["kubectl", "get", "secret", _SECRET, "-n", _PROD_NS, "-o", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    data = (json.loads(proc.stdout).get("data") or {})
    raw = data.get("MICROSOFT_OAUTH_AUTHORITY_TENANT")
    if not raw:
        return None
    tenant = base64.b64decode(raw).decode("utf-8").strip()
    return tenant or None


def _patch_configmap() -> int:
    values = dict(_CONFIG_VALUES_BASE)
    explicit = _explicit_login_authority_from_secrets()
    if explicit:
        values["MICROSOFT_OAUTH_AUTHORITY_TENANT"] = explicit
    patch = json.dumps({"data": values})
    cmd = [
        "kubectl",
        "patch",
        "configmap",
        _CONFIGMAP,
        "-n",
        _PROD_NS,
        "--type",
        "merge",
        "-p",
        patch,
    ]
    print("Patching production ledgerlink-config keys:", ", ".join(sorted(values)))
    for key, value in sorted(values.items()):
        print(f"  {key}={value}")
    return subprocess.run(cmd, check=False).returncode


def _restart() -> int:
    cmd = [
        "kubectl",
        "rollout",
        "restart",
        "deployment/ledgerlink-api",
        "deployment/ledgerlink-worker",
        "deployment/ledgerlink-beat",
        "-n",
        _PROD_NS,
    ]
    print("Restarting production API/worker/beat deployments…")
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Rollout-restart API/worker/beat after patching",
    )
    args = parser.parse_args()

    rc = _patch_configmap()
    if rc != 0:
        return rc

    if args.restart:
        rc = _restart()
        if rc != 0:
            return rc
        print(
            "Waiting for API rollout…\n"
            f"  kubectl rollout status deployment/ledgerlink-api -n {_PROD_NS}"
        )
        return subprocess.run(
            [
                "kubectl",
                "rollout",
                "status",
                "deployment/ledgerlink-api",
                "-n",
                _PROD_NS,
                "--timeout=180s",
            ],
            check=False,
        ).returncode

    print(
        "Patched production OAuth env. Restart API/worker/beat pods to pick up changes:\n"
        "  kubectl rollout restart deployment/ledgerlink-api deployment/ledgerlink-worker "
        f"deployment/ledgerlink-beat -n {_PROD_NS}\n\n"
        "Also ensure Entra app redirect URI includes:\n"
        f"  {_CONFIG_VALUES_BASE['MICROSOFT_OAUTH_REDIRECT_URI']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
