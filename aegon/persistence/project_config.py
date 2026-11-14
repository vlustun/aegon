"""Repository for a project's ``aegon.json`` config (branch + github repo)."""

from __future__ import annotations

import json
from pathlib import Path


class ProjectConfigRepository:
    CONFIG_NAME = "aegon.json"

    def path(self, project: Path) -> Path:
        return project / self.CONFIG_NAME

    def load(self, project: Path) -> dict:
        p = self.path(project)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def save(self, project: Path, cfg: dict) -> None:
        self.path(project).write_text(
            json.dumps(cfg, indent=2) + "\n", encoding="utf-8"
        )
