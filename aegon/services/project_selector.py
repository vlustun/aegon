"""Interactive selection of a new or existing project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aegon.config import Settings
from aegon.domain.plan import slugify
from aegon.persistence.plan_repository import PlanRepository
from aegon.persistence.project_config import ProjectConfigRepository
from aegon.ports.ui import UserInterface


@dataclass(frozen=True)
class ProjectSelection:
    project: Path
    idea: str
    is_new: bool


class ProjectSelector:
    def __init__(
        self,
        ui: UserInterface,
        settings: Settings,
        config_repo: ProjectConfigRepository,
    ) -> None:
        self._ui = ui
        self._settings = settings
        self._config_repo = config_repo

    def choose(self, idea_arg: str) -> ProjectSelection:
        projects_dir = self._settings.projects_dir
        existing = (
            sorted(p.name for p in projects_dir.iterdir() if p.is_dir())
            if projects_dir.is_dir()
            else []
        )

        mode = ""
        while mode not in ("n", "e"):
            prompt = "New or existing project? [n]ew / [e]xisting: "
            if not existing:
                self._ui.notify("(no existing projects yet — starting fresh)")
                mode = "n"
                break
            mode = self._ui.ask(prompt).lower()[:1] or "n"

        if mode == "e":
            return self._choose_existing(existing, idea_arg)
        return self._create_new(idea_arg)

    def _choose_existing(self, existing: list[str], idea_arg: str) -> ProjectSelection:
        projects_dir = self._settings.projects_dir
        self._ui.notify("\nExisting projects:")
        for i, name in enumerate(existing, 1):
            status = PlanRepository(projects_dir / name).status()
            self._ui.notify(f"  {i}) {name:<20} {status}")
        while True:
            pick = self._ui.ask("Pick a number: ")
            if pick.isdigit() and 1 <= int(pick) <= len(existing):
                name = existing[int(pick) - 1]
                break
            self._ui.notify("   (enter a valid number)")
        # Defer "what should we work on?" to the orchestrator: it offers resume
        # first, and only needs an instruction when a new plan is actually made.
        return ProjectSelection(projects_dir / name, idea_arg, False)

    def _create_new(self, idea_arg: str) -> ProjectSelection:
        idea = idea_arg or self._ui.read_multiline("Describe the app you want to build:")
        suggested = slugify(idea)
        name = self._ui.ask(f"Project folder name [{suggested}]: ") or suggested
        name = slugify(name)
        path = self._settings.projects_dir / name
        if path.exists():
            self._ui.notify(f"(a project named '{name}' already exists — continuing in it)")
        path.mkdir(parents=True, exist_ok=True)

        # Per-project config: which GitHub repo this project pushes to.
        repo = self._ui.ask("GitHub repo for this project (git URL, blank to skip): ")
        cfg = {"branch": "main"}
        if repo:
            cfg["github_repo"] = repo
        self._config_repo.save(path, cfg)
        return ProjectSelection(path, idea, True)
