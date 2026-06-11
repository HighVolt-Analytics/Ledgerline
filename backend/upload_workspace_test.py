#!/usr/bin/env python3
"""Upload workspace-test-invoice.pdf to the local API.

Usage (from backend/):
    python upload_workspace_test.py
    python upload_workspace_test.py --email you@example.com --password yourpass

Requires API on http://localhost:8001 (or API_BASE env).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

DEFAULT_FILE = (
    Path(__file__).resolve().parent.parent / "test-assets" / "workspace-test-invoice.pdf"
)
API_BASE = os.environ.get("API_BASE", "http://localhost:8001").rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload workspace test invoice")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--email", default=os.environ.get("TEST_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("TEST_PASSWORD", ""))
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"Missing file: {args.file}", file=sys.stderr)
        print("Run: python test-assets/generate_workspace_test_invoice.py", file=sys.stderr)
        return 1

    token = os.environ.get("API_TOKEN", "").strip()
    headers: dict[str, str] = {}

    if not token:
        if not args.email or not args.password:
            print(
                "Set API_TOKEN or pass --email and --password (or TEST_EMAIL / TEST_PASSWORD).",
                file=sys.stderr,
            )
            return 1
        login = httpx.post(
            f"{API_BASE}/api/auth/login",
            json={"email": args.email, "password": args.password},
            timeout=30.0,
        )
        if login.status_code != 200:
            print(f"Login failed ({login.status_code}): {login.text}", file=sys.stderr)
            return 1
        token = login.json()["data"]["access_token"]

    headers["Authorization"] = f"Bearer {token}"

    with args.file.open("rb") as handle:
        res = httpx.post(
            f"{API_BASE}/api/invoices/upload",
            headers=headers,
            files={"file": (args.file.name, handle, "application/pdf")},
            timeout=120.0,
        )

    if res.status_code == 409:
        print("Duplicate file — this PDF was already uploaded. Change PO/invoice no in the generator and regenerate.")
        return 1
    if res.status_code != 200:
        print(f"Upload failed ({res.status_code}): {res.text}", file=sys.stderr)
        return 1

    inv = res.json()["data"]
    print(f"Uploaded invoice id={inv['id']} status={inv['status']}")
    if inv.get("route_target"):
        print(f"  route_target={inv['route_target']}")
    if inv.get("po_reference"):
        print(f"  po_reference={inv['po_reference']}")
    print("\nNext:")
    print(f"  Inbox:      http://localhost:5173/inbox")
    print(f"  Matrix:     http://localhost:5173/matrix")
    print(f"  Purchases:  http://localhost:5173/purchases  (if PO ref set)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
