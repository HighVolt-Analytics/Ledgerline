"""Sync Stripe secrets from AKS quantum-ledgerlink into backend/.env for local dev."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

_NAMESPACE = "quantum-ledgerlink"
_SECRET = "app-secrets"
_CONFIGMAP = "ledgerlink-config"

_SECRET_KEYS = (
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PLATFORM_BILLING_WEBHOOK_SECRET",
    "STRIPE_CONNECT_CLIENT_ID",
)

_CONFIG_KEYS = (
    "STRIPE_PLATFORM_BILLING_ENABLED",
    "STRIPE_PLATFORM_BILLING_LIVE_ENABLED",
    "STRIPE_PRICE_STUDIO_INR",
    "STRIPE_PRICE_STUDIO_AUD",
    "STRIPE_PRICE_STUDIO_SGD",
)


def _kubectl_json(args: list[str]) -> dict:
    out = subprocess.check_output(["kubectl", *args], text=True)
    return json.loads(out)


def _secret_values() -> dict[str, str]:
    payload = _kubectl_json(["get", "secret", _SECRET, "-n", _NAMESPACE, "-o", "json"])
    out: dict[str, str] = {}
    for key in _SECRET_KEYS:
        raw = payload.get("data", {}).get(key)
        if raw:
            out[key] = base64.b64decode(raw).decode("utf-8")
    return out


def _config_values() -> dict[str, str]:
    payload = _kubectl_json(["get", "configmap", _CONFIGMAP, "-n", _NAMESPACE, "-o", "json"])
    data = payload.get("data", {})
    return {k: str(data[k]) for k in _CONFIG_KEYS if k in data}


def _upsert_env_lines(path: Path, updates: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = text.splitlines()
    seen: set[str] = set()

    def replace_line(key: str, value: str) -> None:
        nonlocal lines
        pattern = re.compile(rf"^{re.escape(key)}=.*$")
        replaced = False
        for idx, line in enumerate(lines):
            if pattern.match(line):
                lines[idx] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")
        seen.add(key)

    for key, value in updates.items():
        replace_line(key, value)

    # Platform billing uses the same Stripe account as Connect in AKS.
    if "STRIPE_SECRET_KEY" in updates:
        replace_line("STRIPE_PLATFORM_BILLING_SECRET_KEY", updates["STRIPE_SECRET_KEY"])

    if not any(line.startswith("# Platform subscription billing") for line in lines):
        lines.extend(
            [
                "",
                "# Platform subscription billing (synced from AKS quantum-ledgerlink)",
                f"STRIPE_PLATFORM_BILLING_ENABLED={updates.get('STRIPE_PLATFORM_BILLING_ENABLED', 'true')}",
            ]
        )

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    try:
        secrets = _secret_values()
        config = _config_values()
    except subprocess.CalledProcessError as exc:
        print(f"kubectl failed: {exc}", file=sys.stderr)
        return 1

    if not secrets.get("STRIPE_SECRET_KEY"):
        print("STRIPE_SECRET_KEY not found in AKS secret", file=sys.stderr)
        return 1

    updates = {
        **secrets,
        **config,
        "STRIPE_PLATFORM_BILLING_ENABLED": config.get(
            "STRIPE_PLATFORM_BILLING_ENABLED", "true"
        ),
        "STRIPE_PLATFORM_BILLING_SUCCESS_URL": "http://localhost:5173/billing?checkout=success",
        "STRIPE_PLATFORM_BILLING_CANCEL_URL": "http://localhost:5173/signup?checkout=cancelled",
    }
    _upsert_env_lines(env_path, updates)

    print(f"Updated Stripe env in {env_path}")
    for key in sorted(updates):
        if key.startswith("STRIPE"):
            print(f"  {key}=***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
