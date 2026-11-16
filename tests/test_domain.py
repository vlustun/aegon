"""Tests for the native (post-refactor) domain API."""

from aegon.domain.plan import (
    Plan,
    Task,
    TestResult,
    count_progress,
    extract_tasks,
    parse_plan,
    parse_tasks,
    read_result,
    slugify,
)


def test_slugify():
    assert slugify("A CLI todo app in Python") == "a-cli-todo-app"
    assert slugify("!!!") == "project"


def test_parse_plan():
    assert parse_plan('x {"a": 1} y') == {"a": 1}
    assert parse_plan("nope") is None


def test_parse_tasks_returns_task_objects():
    tasks = parse_tasks("- [ ] one\n- [x] two\n- [X] three\n")
    assert tasks == [Task("one", False), Task("two", True), Task("three", True)]


def test_count_progress():
    assert count_progress("- [x] a\n- [ ] b\n- [X] c\n") == (2, 3)


def test_extract_tasks():
    assert extract_tasks("1. a\n- b\nplain\n* c") == ["a", "b", "c"]


def test_read_result_returns_enum():
    assert read_result("RESULT: FAIL\nRESULT: PASS") is TestResult.PASS
    assert read_result("RESULT: NONE") is TestResult.NONE
    assert read_result("none") is None
    # str-enum keeps backward-compatible equality with plain strings
    assert read_result("RESULT: PASS") == "PASS"


def test_plan_from_dict_defaults_and_passthrough():
    p = Plan.from_dict({})
    assert p.summary == "—" and p.stack == "—" and p.files == [] and p.steps == []
    p2 = Plan.from_dict({"summary": "s", "stack": "py", "files": ["a"], "steps": ["x"]})
    assert p2.summary == "s" and p2.files == ["a"] and p2.steps == ["x"]
    assert p2.raw["summary"] == "s"
