"""The orchestrator: a thin Facade that prepares a run and sequences stages."""

from __future__ import annotations

from aegon.agents.roles import AgentRoleFactory
from aegon.config import ROLE_MODEL_FIELDS, Settings
from aegon.persistence.plan_repository import PlanRepository
from aegon.persistence.project_config import ProjectConfigRepository
from aegon.pipeline.stage import PipelineAbort, RunContext
from aegon.pipeline.stages import (
    PlanStage,
    PublishStage,
    ScaffoldStage,
    TestFixStage,
    WrapUpStage,
)
from aegon.ports.agent_runner import AgentRunner
from aegon.ports.ui import UserInterface
from aegon.services.project_selector import ProjectSelection, ProjectSelector
from aegon.services.publisher import Publisher


class Orchestrator:
    def __init__(
        self,
        ui: UserInterface,
        runner: AgentRunner,
        roles: AgentRoleFactory,
        settings: Settings,
        selector: ProjectSelector,
        publisher: Publisher,
        config_repo: ProjectConfigRepository,
    ) -> None:
        self._ui = ui
        self._runner = runner
        self._roles = roles
        self._settings = settings
        self._selector = selector
        self._publisher = publisher
        self._config_repo = config_repo

    async def run(self, idea_arg: str) -> None:
        self._ui.notify("\n🜂  Aegon")
        selection = self._selector.choose(idea_arg)
        settings, roles = self._resolve_models(selection)
        ctx, plan_repo = self._prepare(selection)

        stages = [
            PlanStage(self._ui, self._runner, roles),
            ScaffoldStage(self._ui, self._runner, roles, plan_repo),
            TestFixStage(self._ui, self._runner, roles, settings),
            WrapUpStage(self._ui),
            PublishStage(self._publisher),
        ]
        try:
            for stage in stages:
                await stage.run(ctx)
        except PipelineAbort:
            return

        self._ui.notify("\n" + "─" * 60)
        self._ui.notify(
            f"done · ${ctx.total_cost:.4f} · project: {ctx.project}/"
            + ("" if ctx.kept else "  (you marked this run as not kept)")
        )

    def _resolve_models(
        self, selection: ProjectSelection
    ) -> tuple[Settings, AgentRoleFactory]:
        """Apply the project's per-role model overrides (aegon.json "models").

        Defaults come from the injected Settings; a project can override any
        role in its own aegon.json, so the model choice is config → default.
        """
        cfg = self._config_repo.load(selection.project)
        settings = self._settings.with_models(cfg.get("models"))
        if settings is not self._settings:
            picks = ", ".join(
                f"{role}={getattr(settings, field)}"
                for role, field in sorted(ROLE_MODEL_FIELDS.items())
            )
            self._ui.notify(f"→ models (from aegon.json): {picks}")
        return settings, AgentRoleFactory(settings)

    def _prepare(
        self, selection: ProjectSelection
    ) -> tuple[RunContext, PlanRepository]:
        project, idea, is_new = selection.project, selection.idea, selection.is_new
        plan_repo = PlanRepository(project)

        # The build plan (progress.md) is canonical and never overwritten by a
        # task. Each new task on an existing project gets its own plan file.
        resume = False
        plan_path = None

        if is_new:
            plan_path = plan_repo.build_plan_path()
        else:
            unfinished = plan_repo.unfinished_plans()
            if unfinished:
                self._ui.notify("\nUnfinished plans:")
                for i, p in enumerate(unfinished, 1):
                    done, total = plan_repo.progress(p)
                    self._ui.notify(f"  {i}) {plan_repo.label(p):<28} {done}/{total} tasks")
                self._ui.notify("  n) start a new task plan")
                while True:
                    pick = self._ui.ask("Resume which? [number] / [n]ew: ").lower()
                    if pick[:1] == "n":
                        break
                    if pick.isdigit() and 1 <= int(pick) <= len(unfinished):
                        plan_path = unfinished[int(pick) - 1]
                        resume = True
                        break
                    self._ui.notify("   (enter a valid number or 'n')")
            # else: nothing to resume → a new task plan (path set once idea known).

        # A fresh task needs an instruction; a resume does not.
        if not resume and not idea:
            prompt = (
                "Describe the app you want to build:"
                if is_new
                else f"What should we work on in '{project.name}'?"
            )
            idea = self._ui.read_multiline(prompt)

        if plan_path is None:
            plan_path = plan_repo.new_task_plan_path(idea)

        is_build_plan = plan_repo.is_build_plan(plan_path)
        plan_title = "Build Plan" if is_build_plan else "Task Plan"
        html_path = plan_repo.html_for(plan_path)
        rel_plan = plan_path.relative_to(project)

        kind = "new project" if is_new else "existing project"
        self._ui.notify(f"\n{kind}: {project}/")
        if idea:
            self._ui.notify(f"→ task: {idea!r}")
        self._ui.notify(f"→ plan file: {rel_plan}")

        ctx = RunContext(
            project=project,
            idea=idea,
            is_new=is_new,
            plan_path=plan_path,
            html_path=html_path,
            rel_plan=rel_plan,
            resume=resume,
            is_build_plan=is_build_plan,
            plan_title=plan_title,
        )
        return ctx, plan_repo
