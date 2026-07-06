"""Patch AKS staging app-secrets with super-admin portal embed keys.

Usage (from backend/, with kubectl context set to highvolt-aks):

    python scripts/patch_staging_portal_embed_secret.py

Re-run safely — keys are upserted, not duplicated.
"""

from __future__ import annotations

import base64
import subprocess
import sys

_NAMESPACE = "quantum-ledgerlink"
_SECRET = "app-secrets"
_EMBED_TOKEN = "ll_pe_k3_47Kjqq5fe_w4vBaa19jyJCh3hPArn"
_EMBED_EMAIL = "vishnu@highvolt.tech"


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def main() -> int:
    patch = (
        f'{{"data":{{'
        f'"SUPER_ADMIN_PORTAL_EMBED_TOKEN":"{_b64(_EMBED_TOKEN)}",'
        f'"SUPER_ADMIN_PORTAL_EMBED_EMAIL":"{_b64(_EMBED_EMAIL)}"'
        f"}}}}"
    )
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
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print("Failed to patch secret. Is kubectl configured for highvolt-aks?", file=sys.stderr)
        return result.returncode
    print("Patched app-secrets. Restart ledgerlink-api pods to pick up new values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
