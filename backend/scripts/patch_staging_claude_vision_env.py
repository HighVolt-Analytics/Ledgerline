"""Patch AKS staging app-secrets with Claude / Azure AI Visualization env from .env.

Usage (from backend/, kubectl context = highvolt-aks):

    python scripts/patch_staging_claude_vision_env.py

Never prints secret values — only key names and presence.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

_NAMESPACE = "quantum-ledgerlink"
_SECRET = "app-secrets"

# Keys to sync into app-secrets (same pattern as AZURE_AI_FOUNDRY_*).
_SECRET_KEYS = (
    "AZURE_AI_VISUALIZATION_ENDPOINT",
    "AZURE_AI_VISUALIZATION_API_KEY",
    "AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME",
    "AZURE_AI_VISUALIZATION_ANTHROPIC_VERSION",
)

# Optional: do not overwrite staging default provider unless explicitly set
# and this flag is true. Staging currently uses azure_foundry.
_SYNC_VISION_PROVIDER = False


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


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    env = _load_dotenv(env_path)

    values: dict[str, str] = {}
    for key in _SECRET_KEYS:
        val = env.get(key, "").strip()
        if val:
            values[key] = val

    # Accept alternate deployment key name from .env
    if "AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME" not in values:
        alt = env.get("AZURE_AI_VISUALIZATION_DEPLOYMENT", "").strip()
        if alt:
            values["AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME"] = alt

    if _SYNC_VISION_PROVIDER:
        provider = env.get("VISION_LLM_PROVIDER", "").strip()
        if provider:
            values["VISION_LLM_PROVIDER"] = provider

    required = (
        "AZURE_AI_VISUALIZATION_ENDPOINT",
        "AZURE_AI_VISUALIZATION_API_KEY",
        "AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME",
    )
    missing = [k for k in required if not values.get(k)]
    if missing:
        print(f"Missing required keys in .env: {', '.join(missing)}", file=sys.stderr)
        return 1

    if "AZURE_AI_VISUALIZATION_ANTHROPIC_VERSION" not in values:
        values["AZURE_AI_VISUALIZATION_ANTHROPIC_VERSION"] = "2023-06-01"

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
    print(
        "  (values not printed; endpoint/deployment present,",
        f"api_key_len={len(values['AZURE_AI_VISUALIZATION_API_KEY'])})",
    )
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        return rc

    print("Patched staging Claude vision secrets. Restart pods to pick up changes:")
    print(
        "  kubectl rollout restart deployment/ledgerlink-api "
        "deployment/ledgerlink-worker deployment/ledgerlink-beat "
        f"-n {_NAMESPACE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
