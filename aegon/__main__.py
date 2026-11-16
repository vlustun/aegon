"""Composition root: wire concrete adapters into the orchestrator and run.

    python -m aegon
    python -m aegon "a CLI todo app in Python"   # pre-fills the idea
    python -m aegon --file idea.txt               # read the idea from a file
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from aegon.adapters.console_ui import ConsoleUI
from aegon.adapters.git_vcs import GitVersionControl
from aegon.adapters.sdk_runner import SdkAgentRunner
from aegon.agents.roles import AgentRoleFactory
from aegon.config import Settings
from aegon.persistence.project_config import ProjectConfigRepository
from aegon.pipeline.orchestrator import Orchestrator
from aegon.services.project_selector import ProjectSelector
from aegon.services.publisher import Publisher


def _read_idea_arg(args: list[str]) -> str:
    if args and args[0] in ("--file", "-f"):
        if len(args) < 2:
            print("usage: python -m aegon --file <path>")
            raise SystemExit(1)
        return Path(args[1]).read_text(encoding="utf-8").strip()
    if args:
        return " ".join(args)
    return ""


def build_orchestrator(settings: Settings | None = None) -> Orchestrator:
    settings = settings or Settings()
    ui = ConsoleUI()
    runner = SdkAgentRunner(ui)
    roles = AgentRoleFactory(settings)
    config_repo = ProjectConfigRepository()
    vcs = GitVersionControl(ui)
    selector = ProjectSelector(ui, settings, config_repo)
    publisher = Publisher(ui, vcs, config_repo, settings)
    return Orchestrator(ui, runner, roles, settings, selector, publisher)


def main() -> None:
    idea_arg = _read_idea_arg(sys.argv[1:])
    orchestrator = build_orchestrator()
    asyncio.run(orchestrator.run(idea_arg))


if __name__ == "__main__":
    main()
