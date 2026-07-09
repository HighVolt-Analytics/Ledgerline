"""Golden eval harness tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_GOLDEN_ROOT = Path(__file__).resolve().parent / "fixtures" / "golden"


def test_golden_manifest_lists_fixtures() -> None:
    manifest = json.loads((_GOLDEN_ROOT / "manifest.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in manifest["fixtures"]}
    assert "qty_only_spectra" in ids
    assert len(ids) >= 10


def test_eval_extraction_golden_script_runs() -> None:
    script = Path(__file__).resolve().parent.parent / "scripts" / "eval_extraction_golden.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(script.parent.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
