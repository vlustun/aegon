"""Aegon — back-compat shim.

The harness was refactored into the ``aegon`` package (ports/adapters +
a staged pipeline). This module keeps the historical entry point and the public
pure-function API working:

    python harness.py                       # run the harness
    python harness.py "a CLI todo app"      # pre-fill the idea
    python harness.py --file idea.txt

New code should import from ``aegon`` directly and run ``python -m aegon``.
"""

from __future__ import annotations

from pathlib import Path

from aegon.__main__ import main
from aegon.adapters.git_vcs import make_branch_name, parse_github_slug
from aegon.config import Settings
from aegon.domain.plan import (
    Plan,
    count_progress,
    extract_tasks,
    parse_plan,
    parse_tasks,
    read_result,
    slugify,
)
from aegon.persistence.project_config import ProjectConfigRepository
from aegon.rendering import html as _html
from aegon.rendering import markdown as _markdown
from aegon.services.publisher import ensure_gitignore

_config_repo = ProjectConfigRepository()

__all__ = [
    "main",
    "slugify",
    "parse_plan",
    "extract_tasks",
    "read_result",
    "parse_github_slug",
    "make_branch_name",
    "ensure_gitignore",
    "tasks_from_md",
    "plan_progress",
    "write_progress_md",
    "write_progress_md_fallback",
    "write_plan_html",
    "load_config",
    "save_config",
]


# --- compatibility wrappers (old signatures / return types) -----------------
def tasks_from_md(progress_md: Path) -> list[tuple[str, bool]]:
    """Read tasks and their checked state from a plan file (legacy tuple shape)."""
    tasks = parse_tasks(progress_md.read_text(encoding="utf-8"))
    return [(t.text, t.done) for t in tasks]


def plan_progress(plan_md: Path) -> tuple[int, int]:
    """Count (checked, total) task checkboxes in a plan file."""
    return count_progress(plan_md.read_text(encoding="utf-8"))


def write_progress_md(data: dict, out_path: Path, idea: str,
                      title: str = "Build Plan") -> Path:
    return _markdown.write_progress_md(Plan.from_dict(data), out_path, idea, title)


def write_progress_md_fallback(raw: str, out_path: Path, idea: str,
                               title: str = "Build Plan") -> Path:
    return _markdown.write_progress_md_fallback(raw, out_path, idea, title)


def write_plan_html(data: dict, out_path: Path, idea: str,
                    progress_md: Path | None = None) -> Path:
    return _html.write_plan_html(Plan.from_dict(data), out_path, idea, progress_md)


def load_config(project: Path) -> dict:
    return _config_repo.load(project)


def save_config(project: Path, cfg: dict) -> None:
    _config_repo.save(project, cfg)


if __name__ == "__main__":
    main()
