"""Writes ``run.json`` — a summary of the last run for later inspection."""

from __future__ import annotations

import json
from pathlib import Path


def write_run_log(project: Path, data: dict) -> Path:
    out = project / "run.json"
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out
