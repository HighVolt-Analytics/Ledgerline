"""Patch AKS staging app-secrets and ledgerlink-config with OAuth / Meta env from .env.

Usage (from backend/, kubectl context = highvolt-aks):

    python scripts/patch_staging_oauth_env.py

Reads backend/.env for secret values; redirect URIs and FRONTEND_URL use staging URLs.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

_NAMESPACE = "quantum-ledgerlink"
_SECRET = "app-secrets"
_CONFIGMAP = "ledgerlink-config"
_STAGING_BASE = "https://staging.highvolt.tech/ledgerlink"

_ENV_KEYS_SECRETS = (
    "META_APP_ID",
    "META_APP_SECRET",
    "META_WEBHOOK_VERIFY_TOKEN",
    "WHATSAPP_GRAPH_API_VERSION",
    "WHATSAPP_OAUTH_SCOPES",
    "WHATSAPP_OAUTH_REDIRECT_URI",
    "WHATSAPP_OAUTH_FRONTEND_RETURN_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "MICROSOFT_OAUTH_CLIENT_ID",
    "MICROSOFT_OAUTH_CLIENT_SECRET",
    "MICROSOFT_OAUTH_AUTHORITY_TENANT",
    "MICROSOFT_OAUTH_PUBLIC_CLIENT",
    "GOOGLE_OAUTH_REDIRECT_URI",
    "MICROSOFT_OAUTH_REDIRECT_URI",
    "GMAIL_OAUTH_REDIRECT_URI",
    "FRONTEND_URL",
)


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _staging_values(env: dict[str, str]) -> dict[str, str]:
    values = {k: env[k] for k in _ENV_KEYS_SECRETS if env.get(k)}
    values["WHATSAPP_OAUTH_REDIRECT_URI"] = f"{_STAGING_BASE}/auth/whatsapp/callback"
    values["WHATSAPP_OAUTH_FRONTEND_RETURN_URL"] = f"{_STAGING_BASE}/integrations"
    values["GMAIL_OAUTH_REDIRECT_URI"] = (
        f"{_STAGING_BASE}/api/mailboxes/gmail/oauth/callback"
    )
    values["GOOGLE_OAUTH_REDIRECT_URI"] = (
        f"{_STAGING_BASE}/api/auth/oauth/google/callback"
    )
    values["MICROSOFT_OAUTH_REDIRECT_URI"] = (
        f"{_STAGING_BASE}/api/auth/oauth/microsoft/callback"
    )
    values["FRONTEND_URL"] = _STAGING_BASE
    if "MICROSOFT_OAUTH_PUBLIC_CLIENT" not in values:
        values["MICROSOFT_OAUTH_PUBLIC_CLIENT"] = "false"
    # SaaS multi-tenant login: keep /common unless MICROSOFT_OAUTH_AUTHORITY_TENANT
    # is explicitly set in .env. Never copy AZURE_TENANT_ID into login authority
    # (that GUID is for Graph/mailbox only; overwriting here undoes multi-tenant login).
    explicit = (values.get("MICROSOFT_OAUTH_AUTHORITY_TENANT") or "").strip()
    if explicit:
        values["MICROSOFT_OAUTH_AUTHORITY_TENANT"] = explicit
    else:
        values["MICROSOFT_OAUTH_AUTHORITY_TENANT"] = "common"
    return values


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _patch_secret(values: dict[str, str]) -> int:
    data = {k: _b64(v) for k, v in values.items()}
    patch = json.dumps({"data": data})
    cmd = [
        "kubectl",
        "patch",
        "secret",
        _SECRET,
        "-n",
        _NAMESPACE,
        "--type",
        "merge",
        "-p",
        patch,
    ]
    print("Patching app-secrets keys:", ", ".join(sorted(values)))
    return subprocess.run(cmd, check=False).returncode


def _patch_configmap(values: dict[str, str]) -> int:
    config_keys = (
        "FRONTEND_URL",
        "GOOGLE_OAUTH_REDIRECT_URI",
        "MICROSOFT_OAUTH_REDIRECT_URI",
        "MICROSOFT_OAUTH_PUBLIC_CLIENT",
        "MICROSOFT_OAUTH_AUTHORITY_TENANT",
        "GMAIL_OAUTH_REDIRECT_URI",
        "WHATSAPP_OAUTH_REDIRECT_URI",
        "WHATSAPP_OAUTH_FRONTEND_RETURN_URL",
    )
    data = {k: values[k] for k in config_keys if k in values}
    patch = json.dumps({"data": data})
    cmd = [
        "kubectl",
        "patch",
        "configmap",
        _CONFIGMAP,
        "-n",
        _NAMESPACE,
        "--type",
        "merge",
        "-p",
        patch,
    ]
    print("Patching ledgerlink-config keys:", ", ".join(sorted(data)))
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    values = _staging_values(_load_dotenv(env_path))
    missing = [
        k
        for k in (
            "META_APP_ID",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "MICROSOFT_OAUTH_CLIENT_ID",
            "MICROSOFT_OAUTH_CLIENT_SECRET",
        )
        if not values.get(k)
    ]
    if missing:
        print(f"Missing required keys in .env: {', '.join(missing)}", file=sys.stderr)
        return 1

    rc = _patch_secret(values)
    if rc != 0:
        return rc
    rc = _patch_configmap(values)
    if rc != 0:
        return rc

    print("Patched staging OAuth/Meta env. Restart API/worker/beat pods to pick up changes:")
    print(
        "  kubectl rollout restart deployment/ledgerlink-api deployment/ledgerlink-worker "
        f"deployment/ledgerlink-beat -n {_NAMESPACE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
