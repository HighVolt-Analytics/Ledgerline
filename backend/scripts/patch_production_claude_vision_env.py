"""Patch AKS production app-secrets with Claude / Azure AI Visualization env.

Copies keys from staging app-secrets by default (same cluster, known-good),
or from backend/.env when --from-env is passed.

Usage (from backend/, kubectl context = highvolt-aks):

    python scripts/patch_production_claude_vision_env.py
    python scripts/patch_production_claude_vision_env.py --from-env
    python scripts/patch_production_claude_vision_env.py --restart

Never prints secret values — only key names and presence.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

_STAGING_NS = "quantum-ledgerlink"
_PROD_NS = "quantum-ledgerlink-prod"
_SECRET = "app-secrets"

_SECRET_KEYS = (
    "AZURE_AI_VISUALIZATION_ENDPOINT",
    "AZURE_AI_VISUALIZATION_API_KEY",
    "AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME",
    "AZURE_AI_VISUALIZATION_ANTHROPIC_VERSION",
)

_REQUIRED = (
    "AZURE_AI_VISUALIZATION_ENDPOINT",
    "AZURE_AI_VISUALIZATION_API_KEY",
    "AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME",
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


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _kubectl_json(args: list[str]) -> dict:
    proc = subprocess.run(
        ["kubectl", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "kubectl failed")
    return json.loads(proc.stdout)


def _values_from_staging() -> dict[str, str]:
    secret = _kubectl_json(
        ["get", "secret", _SECRET, "-n", _STAGING_NS, "-o", "json"]
    )
    data = secret.get("data") or {}
    values: dict[str, str] = {}
    for key in _SECRET_KEYS:
        raw = data.get(key)
        if not raw:
            continue
        values[key] = base64.b64decode(raw).decode("utf-8")
    return values


def _values_from_env() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    env = _load_dotenv(env_path)
    values: dict[str, str] = {}
    for key in _SECRET_KEYS:
        val = env.get(key, "").strip()
        if val:
            values[key] = val
    if "AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME" not in values:
        alt = env.get("AZURE_AI_VISUALIZATION_DEPLOYMENT", "").strip()
        if alt:
            values["AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME"] = alt
    return values


def _patch_prod(values: dict[str, str]) -> int:
    data = {k: _b64(v) for k, v in values.items()}
    patch = json.dumps({"data": data})
    cmd = [
        "kubectl",
        "patch",
        "secret",
        _SECRET,
        "-n",
        _PROD_NS,
        "--type",
        "merge",
        "-p",
        patch,
    ]
    print("Patching production app-secrets keys:", ", ".join(sorted(values)))
    print(
        "  (values not printed; endpoint/deployment present,",
        f"api_key_len={len(values['AZURE_AI_VISUALIZATION_API_KEY'])})",
    )
    return subprocess.run(cmd, check=False).returncode


def _restart_prod() -> int:
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
    print("Restarting production deployments:", " ".join(cmd[3:]))
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch production Claude Vision AKS secrets"
    )
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="Read values from backend/.env instead of staging app-secrets",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Also restart production API/worker/beat after patching",
    )
    args = parser.parse_args()

    try:
        values = _values_from_env() if args.from_env else _values_from_staging()
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"Failed to load Claude vision secrets: {exc}", file=sys.stderr)
        return 1

    if "AZURE_AI_VISUALIZATION_ANTHROPIC_VERSION" not in values:
        values["AZURE_AI_VISUALIZATION_ANTHROPIC_VERSION"] = "2023-06-01"

    missing = [k for k in _REQUIRED if not values.get(k, "").strip()]
    if missing:
        source = "backend/.env" if args.from_env else f"staging {_SECRET}"
        print(f"Missing required keys in {source}: {', '.join(missing)}", file=sys.stderr)
        return 1

    rc = _patch_prod(values)
    if rc != 0:
        return rc

    print(f"Patched production Claude vision secrets in {_PROD_NS}/{_SECRET}.")
    if args.restart:
        return _restart_prod()

    print("Restart pods to pick up changes:")
    print(
        "  kubectl rollout restart deployment/ledgerlink-api "
        "deployment/ledgerlink-worker deployment/ledgerlink-beat "
        f"-n {_PROD_NS}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
