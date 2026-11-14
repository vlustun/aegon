"""Tests for the repository layer."""

from aegon.persistence.plan_repository import PlanRepository
from aegon.persistence.project_config import ProjectConfigRepository


def test_config_round_trip(tmp_path):
    repo = ProjectConfigRepository()
    assert repo.load(tmp_path) == {}
    repo.save(tmp_path, {"branch": "main", "github_repo": "x"})
    assert repo.load(tmp_path) == {"branch": "main", "github_repo": "x"}
    assert repo.path(tmp_path).name == "aegon.json"


def test_plan_paths_and_build_plan_detection(tmp_path):
    repo = PlanRepository(tmp_path)
    bp = repo.build_plan_path()
    assert bp == tmp_path / "progress.md"
    assert repo.is_build_plan(bp)
    assert repo.html_for(bp) == tmp_path / "plan.html"
    task_plan = repo.new_task_plan_path("my task")
    assert task_plan.parent == tmp_path / "plans"
    assert task_plan.name.startswith("my-task-")
    assert not repo.is_build_plan(task_plan)
    assert repo.html_for(task_plan) == task_plan.with_suffix(".html")


def test_discovery_and_status(tmp_path):
    repo = PlanRepository(tmp_path)
    assert repo.status() == "no plan"

    repo.build_plan_path().write_text("## Tasks\n\n- [x] a\n- [ ] b\n")
    assert repo.progress(repo.build_plan_path()) == (1, 2)
    assert "build 1/2" in repo.status()

    plans = repo.plans_dir()
    plans.mkdir()
    (plans / "t1.md").write_text("- [ ] x\n")
    (plans / "t2.md").write_text("- [x] y\n")
    assert len(repo.list_task_plans()) == 2
    assert "task plan" in repo.status()
    # unfinished = build plan (has [ ]) + t1 (has [ ]); t2 is complete
    unfinished = repo.unfinished_plans()
    names = {p.name for p in unfinished}
    assert "progress.md" in names and "t1.md" in names and "t2.md" not in names
    assert repo.label(repo.build_plan_path()) == "build plan"
    assert repo.label(plans / "t1.md") == "t1"
