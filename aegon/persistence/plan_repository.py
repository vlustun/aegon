"""Repository for plan files: the canonical build plan plus per-task plans.

Centralizes every path convention and discovery/progress query that was
previously scattered across free functions, so the pipeline depends on one
object instead of a dozen helpers (SRP + a single place to change the layout).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from aegon.domain.plan import count_progress, slugify


class PlanRepository:
    def __init__(self, project: Path) -> None:
        self.project = project

    # --- paths -------------------------------------------------------------
    def build_plan_path(self) -> Path:
        """The canonical build plan (kept at the project root for back-compat)."""
        return self.project / "progress.md"

    def plans_dir(self) -> Path:
        return self.project / "plans"

    def new_task_plan_path(self, idea: str) -> Path:
        """A fresh per-task plan file: plans/<slug>-<timestamp>.md."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = slugify(idea) if idea else "task"
        return self.plans_dir() / f"{slug}-{stamp}.md"

    def html_for(self, plan_path: Path) -> Path:
        """The .html render path for a plan file.

        The build plan keeps the historical ``plan.html`` name; a per-task plan
        gets an .html sibling next to it.
        """
        if plan_path == self.build_plan_path():
            return self.project / "plan.html"
        return plan_path.with_suffix(".html")

    def is_build_plan(self, plan_path: Path) -> bool:
        return plan_path == self.build_plan_path()

    # --- discovery ---------------------------------------------------------
    def list_task_plans(self) -> list[Path]:
        """Per-task plans, newest first."""
        d = self.plans_dir()
        return sorted(d.glob("*.md"), reverse=True) if d.is_dir() else []

    def all_plans(self) -> list[Path]:
        """The build plan (if any) followed by every per-task plan."""
        plans: list[Path] = []
        bp = self.build_plan_path()
        if bp.exists():
            plans.append(bp)
        plans.extend(self.list_task_plans())
        return plans

    def unfinished_plans(self) -> list[Path]:
        return [
            p for p in self.all_plans()
            if "- [ ]" in p.read_text(encoding="utf-8")
        ]

    def label(self, plan_path: Path) -> str:
        """Human-readable name for a plan file in listings."""
        if self.is_build_plan(plan_path):
            return "build plan"
        return plan_path.stem

    # --- progress ----------------------------------------------------------
    def progress(self, plan_path: Path) -> tuple[int, int]:
        """Count (checked, total) task checkboxes in a plan file."""
        return count_progress(plan_path.read_text(encoding="utf-8"))

    def status(self) -> str:
        """One-line status for the project picker: build progress + task count."""
        tasks_n = len(self.list_task_plans())
        extra = (
            f"  (+{tasks_n} task plan{'s' if tasks_n != 1 else ''})"
            if tasks_n else ""
        )
        bp = self.build_plan_path()
        if not bp.exists():
            return "no plan" if not tasks_n else f"no build plan{extra}"
        done, total = self.progress(bp)
        if total == 0:
            base = "no tasks"
        elif done == 0:
            base = f"build 0/{total}  (not started)"
        elif done >= total:
            base = f"build {done}/{total}  (complete)"
        else:
            base = f"build {done}/{total}"
        return base + extra
