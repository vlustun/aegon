"""End-to-end orchestrator test using only fakes — no SDK, network or git.

This is the concrete payoff of the refactor: the full plan→scaffold→test→wrap-up
→publish pipeline is exercised in-memory and deterministically.
"""

import asyncio

from aegon.agents.roles import AgentRoleFactory
from aegon.config import Settings
from aegon.persistence.project_config import ProjectConfigRepository
from aegon.pipeline.orchestrator import Orchestrator
from aegon.ports.ui import Decision
from aegon.services.project_selector import ProjectSelector
from aegon.services.publisher import Publisher

from tests.fakes import FakeAgentRunner, FakeUI, FakeVCS

PLAN_JSON = (
    '{"summary": "todo", "stack": "python", '
    '"files": [{"path": "app.py", "purpose": "entry"}], '
    '"steps": ["scaffold app", "add tests"]}'
)


def _build(tmp_path, ui, runner):
    settings = Settings(projects_dir=tmp_path / "projects")
    config_repo = ProjectConfigRepository()
    roles = AgentRoleFactory(settings)
    selector = ProjectSelector(ui, settings, config_repo)
    publisher = Publisher(ui, FakeVCS(), config_repo, settings)
    return Orchestrator(ui, runner, roles, settings, selector, publisher)


def test_new_project_full_run(tmp_path):
    ui = FakeUI(
        answers=["", ""],  # folder name (accept default), github repo (skip)
        decisions=[
            Decision.APPROVE,  # accept the plan
            Decision.QUIT,     # decline running the test suite (skip)
            Decision.APPROVE,  # keep the result
        ],
    )
    runner = FakeAgentRunner({"planner": PLAN_JSON, "scaffolder": "created app.py"})
    orch = _build(tmp_path, ui, runner)

    asyncio.run(orch.run("a todo app"))

    project = tmp_path / "projects" / "a-todo-app"
    assert (project / "progress.md").exists()
    assert (project / "plan.html").exists()
    assert (project / "aegon.json").exists()
    run_log = (project / "run.json").read_text()
    assert '"kept": true' in run_log
    assert '"test_result": null' in run_log

    # the pipeline dispatched planner then scaffolder, in order
    labels = [label for label, _ in runner.calls]
    assert labels == ["planner", "scaffolder"]

    # progress.md carries the planned tasks as unchecked boxes
    progress = (project / "progress.md").read_text()
    assert "- [ ] scaffold app" in progress
    assert "- [ ] add tests" in progress


def test_quit_at_plan_aborts(tmp_path):
    ui = FakeUI(answers=["", ""], decisions=[Decision.QUIT])  # quit at plan
    runner = FakeAgentRunner({"planner": PLAN_JSON})
    orch = _build(tmp_path, ui, runner)

    asyncio.run(orch.run("a todo app"))

    project = tmp_path / "projects" / "a-todo-app"
    # plan file was written before the abort, but scaffolder never ran
    assert (project / "progress.md").exists()
    assert not (project / "run.json").exists()
    assert [label for label, _ in runner.calls] == ["planner"]
