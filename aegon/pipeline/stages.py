"""Concrete pipeline stages: plan, scaffold, test/fix, wrap-up, publish."""

from __future__ import annotations

from aegon.agents.roles import AgentRoleFactory
from aegon.config import Settings
from aegon.domain.plan import Plan, TestResult, parse_plan, read_result
from aegon.persistence.plan_repository import PlanRepository
from aegon.persistence.run_log import write_run_log
from aegon.pipeline.stage import PipelineAbort, RunContext, Stage
from aegon.ports.agent_runner import AgentRunner
from aegon.ports.ui import Decision, UserInterface
from aegon.rendering import (
    format_plan,
    write_plan_html,
    write_progress_md,
    write_progress_md_fallback,
)
from aegon.services.publisher import Publisher


class PlanStage(Stage):
    """Produce (or resume, or reuse) the plan checklist the scaffolder works from."""

    name = "plan"

    def __init__(
        self,
        ui: UserInterface,
        runner: AgentRunner,
        roles: AgentRoleFactory,
    ) -> None:
        self._ui = ui
        self._runner = runner
        self._roles = roles

    async def run(self, ctx: RunContext) -> None:
        user_plan_md = ctx.project / "plan.md"

        if ctx.resume:
            ctx.plan_text = ctx.plan_path.read_text(encoding="utf-8")
            self._ui.notify(f"resuming {ctx.rel_plan} (continuing the unchecked tasks)")
            return

        if ctx.is_build_plan and user_plan_md.exists():
            self._use_user_plan(ctx, user_plan_md)
            return

        await self._plan_with_agent(ctx)

    def _use_user_plan(self, ctx: RunContext, user_plan_md) -> None:
        # A plan.md you placed in the project is treated as YOUR build plan: the
        # planner is skipped and plan.md is never overwritten; the checkbox file
        # is derived from it so tasks can be ticked.
        plan = user_plan_md.read_text(encoding="utf-8")
        self._ui.notify(
            f"using your {user_plan_md} as the plan (it will not be overwritten)"
        )
        if not ctx.plan_path.exists():
            write_progress_md_fallback(plan, ctx.plan_path, ctx.idea, title=ctx.plan_title)
            self._ui.notify(f"   (created {ctx.rel_plan} to track task progress)")
        else:
            self._ui.notify(f"   (keeping existing {ctx.rel_plan} for progress tracking)")
        ctx.plan_text = ctx.plan_path.read_text(encoding="utf-8")

    async def _plan_with_agent(self, ctx: RunContext) -> None:
        context = "" if ctx.is_new else (
            "\nThis is an EXISTING project; read its current files before planning."
        )
        role = self._roles.planner(is_new=ctx.is_new)
        planner_cwd = None if ctx.is_new else str(ctx.project)
        plan_prompt = f"App / task: {ctx.idea}{context}"

        while True:
            result = await self._runner.run(role, plan_prompt, cwd=planner_cwd)
            ctx.add_cost(result.cost_usd)
            plan_text = result.text
            data = parse_plan(plan_text)
            # Write the checkbox plan file now so it always exists (structured if
            # the JSON parsed, else from raw text).
            if data:
                plan_obj = Plan.from_dict(data)
                ctx.plan_data = plan_obj
                write_progress_md(plan_obj, ctx.plan_path, ctx.idea, title=ctx.plan_title)
                self._ui.notify(format_plan(plan_obj))  # quick glance in the terminal
                ctx.html_path = write_plan_html(
                    plan_obj, ctx.html_path, ctx.idea, ctx.plan_path
                )
                opened = self._ui.open_in_browser(ctx.html_path)
                self._ui.notify(
                    f"\n   plan: {ctx.rel_plan}  ·  {ctx.html_path.name}"
                    + ("  (opened)" if opened else "")
                )
            else:
                write_progress_md_fallback(
                    plan_text, ctx.plan_path, ctx.idea, title=ctx.plan_title
                )
                self._ui.notify(plan_text)
                self._ui.notify(f"\n   plan: {ctx.rel_plan}")

            decision, feedback = self._ui.checkpoint("Accept this plan?", allow_revise=True)
            if decision == Decision.QUIT:
                self._ui.notify(f"\naborted at plan stage. ({ctx.rel_plan} was written)")
                raise PipelineAbort()
            if decision == Decision.APPROVE:
                break
            plan_prompt = (
                f"App / task: {ctx.idea}{context}\n\nPrevious plan:\n{plan_text}\n\n"
                f"Revise the plan per this feedback: {feedback}"
            )

        # Hand the checkbox file to the scaffolder to tick off.
        ctx.plan_text = ctx.plan_path.read_text(encoding="utf-8")


class ScaffoldStage(Stage):
    """Create/update files per the plan; the agent ticks tasks off as it goes."""

    name = "scaffold"

    def __init__(
        self,
        ui: UserInterface,
        runner: AgentRunner,
        roles: AgentRoleFactory,
        plan_repo: PlanRepository,
    ) -> None:
        self._ui = ui
        self._runner = runner
        self._roles = roles
        self._plan_repo = plan_repo

    async def run(self, ctx: RunContext) -> None:
        prompt = (
            f"App / task: {ctx.idea}\n\nPlan checklist file: {ctx.rel_plan}\n"
            f"Plan contents:\n{ctx.plan_text}\n\nWork through the unchecked ('- [ ]') "
            f"tasks now, creating or updating the files, and tick each task off in "
            f"{ctx.rel_plan} as you complete it."
        )
        result = await self._runner.run(
            self._roles.scaffolder(), prompt, cwd=str(ctx.project)
        )
        ctx.add_cost(result.cost_usd)
        ctx.scaffold_report = result.text

        if ctx.plan_path.exists():
            done, total = self._plan_repo.progress(ctx.plan_path)
            self._ui.notify(
                f"\n   progress: {done}/{total} tasks checked in {ctx.rel_plan}"
            )
            # Refresh the plan HTML so its checkboxes reflect the scaffolder's work.
            if ctx.plan_data:
                write_plan_html(ctx.plan_data, ctx.html_path, ctx.idea, ctx.plan_path)


class TestFixStage(Stage):
    """Run the test suite and, on failure, loop Tester↔Fixer up to a limit."""

    name = "test+fix"

    def __init__(
        self,
        ui: UserInterface,
        runner: AgentRunner,
        roles: AgentRoleFactory,
        settings: Settings,
    ) -> None:
        self._ui = ui
        self._runner = runner
        self._roles = roles
        self._settings = settings

    async def run(self, ctx: RunContext) -> None:
        decision, _ = self._ui.checkpoint(
            "Run the test suite? (this executes shell commands in the project)"
        )
        if decision != Decision.APPROVE:
            self._ui.notify("skipped testing.")
            ctx.test_result = None
            return

        max_attempts = self._settings.max_fix_attempts
        for attempt in range(1, max_attempts + 1):
            label = f"tester (attempt {attempt}/{max_attempts})"
            result = await self._runner.run(
                self._roles.tester(label),
                "Run the project's full test suite and end with the RESULT line.",
                cwd=str(ctx.project),
            )
            ctx.add_cost(result.cost_usd)
            outcome = read_result(result.text)

            if outcome == TestResult.PASS:
                self._ui.notify(f"\n✓ tests pass (attempt {attempt}).")
                ctx.test_result = TestResult.PASS
                return
            if outcome == TestResult.NONE:
                self._ui.notify("\nno test suite found — nothing to run.")
                ctx.test_result = TestResult.NONE
                return

            self._ui.notify(f"\n✗ tests failing (attempt {attempt}).")
            if attempt == max_attempts:
                break
            self._ui.notify("   → handing the failures to the fixer…")
            fix_label = f"fixer (attempt {attempt}/{max_attempts})"
            fix = await self._runner.run(
                self._roles.fixer(fix_label),
                f"App / task: {ctx.idea}\n\nFailing test output:\n\n{result.text}\n\n"
                "Fix the code so the tests pass.",
                cwd=str(ctx.project),
            )
            ctx.add_cost(fix.cost_usd)

        self._ui.notify(
            "\ntests still failing after max attempts — leaving the code to inspect."
        )
        ctx.test_result = TestResult.FAIL


class WrapUpStage(Stage):
    """Ask whether to keep the result and persist the run log."""

    name = "wrap-up"

    def __init__(self, ui: UserInterface) -> None:
        self._ui = ui

    async def run(self, ctx: RunContext) -> None:
        decision, _ = self._ui.checkpoint("All done. Keep this result?")
        ctx.kept = decision == Decision.APPROVE
        write_run_log(
            ctx.project,
            {
                "idea": ctx.idea,
                "is_new": ctx.is_new,
                "plan_file": str(ctx.rel_plan),
                "resumed": ctx.resume,
                "plan": ctx.plan_text,
                "scaffold_report": ctx.scaffold_report,
                "test_result": ctx.test_result,
                "kept": ctx.kept,
                "cost_usd": ctx.total_cost,
            },
        )


class PublishStage(Stage):
    """Commit + open a PR for the build — only if the user kept the result."""

    name = "publish"

    def __init__(self, publisher: Publisher) -> None:
        self._publisher = publisher

    async def run(self, ctx: RunContext) -> None:
        if not ctx.kept:
            return
        self._publisher.publish(ctx.project, ctx.idea)
