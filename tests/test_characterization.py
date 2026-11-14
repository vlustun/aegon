"""Characterization tests for the pre-refactor harness.

These lock in the observable behavior of the pure logic in ``harness.py`` so the
SOLID/package refactor can be shown to preserve it. They deliberately avoid the
SDK, network and subprocess; only pure functions and file-on-disk helpers are
exercised.

After the refactor the same tests are re-pointed at the new modules (see
``tests/test_domain.py``) and must still pass unchanged.
"""

import harness


# --- slugify ---------------------------------------------------------------
def test_slugify_basic():
    assert harness.slugify("A CLI todo app in Python") == "a-cli-todo-app"


def test_slugify_strips_punctuation_and_caps_words():
    assert harness.slugify("Hello, World!! Foo Bar Baz") == "hello-world-foo-bar"


def test_slugify_empty_falls_back_to_project():
    assert harness.slugify("!!!") == "project"
    assert harness.slugify("") == "project"


# --- parse_plan ------------------------------------------------------------
def test_parse_plan_extracts_json_object():
    text = 'prose before {"summary": "x", "steps": ["a", "b"]} prose after'
    assert harness.parse_plan(text) == {"summary": "x", "steps": ["a", "b"]}


def test_parse_plan_returns_none_on_garbage():
    assert harness.parse_plan("no json here") is None
    assert harness.parse_plan("{not valid json}") is None


# --- read_result (tester sentinel) -----------------------------------------
def test_read_result_last_marker_wins():
    assert harness.read_result("RESULT: FAIL\nRESULT: PASS") == "PASS"
    assert harness.read_result("blah\nRESULT: NONE") == "NONE"
    assert harness.read_result("no marker at all") is None


# --- github slug + branch name --------------------------------------------
def test_parse_github_slug_https_and_ssh():
    assert harness.parse_github_slug("https://github.com/owner/repo.git") == "owner/repo"
    assert harness.parse_github_slug("git@github.com:owner/repo.git") == "owner/repo"
    assert harness.parse_github_slug("not a url") is None


def test_make_branch_name_shape(tmp_path):
    name = harness.make_branch_name(tmp_path / "proj", "My Cool Idea")
    assert name.startswith("aegon/my-cool-idea-")
    assert len(name) <= 60


# --- task parsing + progress on disk ---------------------------------------
def test_tasks_from_md_reads_checkboxes(tmp_path):
    md = tmp_path / "progress.md"
    md.write_text("- [ ] one\n- [x] two\n- [X] three\nnot a task\n")
    assert harness.tasks_from_md(md) == [("one", False), ("two", True), ("three", True)]


def test_plan_progress_counts(tmp_path):
    md = tmp_path / "progress.md"
    md.write_text("- [ ] a\n- [x] b\n- [X] c\n")
    assert harness.plan_progress(md) == (2, 3)


def test_extract_tasks_from_freeform():
    text = "1. first\n- second\n* third\nplain line\n2) fourth"
    assert harness.extract_tasks(text) == ["first", "second", "third", "fourth"]


# --- progress.md writer round-trips through the task parser -----------------
def test_write_progress_md_round_trip(tmp_path):
    data = {
        "summary": "s",
        "stack": "python",
        "files": [{"path": "a.py", "purpose": "entry"}],
        "steps": ["step one", "step two"],
    }
    out = tmp_path / "progress.md"
    harness.write_progress_md(data, out, "an idea", title="Build Plan")
    text = out.read_text()
    assert "# Build Plan" in text
    assert "- [ ] step one" in text
    assert harness.plan_progress(out) == (0, 2)
    assert [t for t, _ in harness.tasks_from_md(out)] == ["step one", "step two"]


def test_write_progress_md_fallback_makes_resumable_plan(tmp_path):
    out = tmp_path / "plan.md"
    harness.write_progress_md_fallback("1. do a\n2. do b", out, "idea")
    assert harness.plan_progress(out) == (0, 2)


# --- config persistence ----------------------------------------------------
def test_config_save_load_round_trip(tmp_path):
    harness.save_config(tmp_path, {"branch": "main", "github_repo": "x"})
    assert harness.load_config(tmp_path) == {"branch": "main", "github_repo": "x"}


def test_load_config_missing_is_empty(tmp_path):
    assert harness.load_config(tmp_path) == {}


# --- gitignore helper ------------------------------------------------------
def test_ensure_gitignore_appends_only_missing(tmp_path):
    harness.ensure_gitignore(tmp_path, ["aegon.json", "run.json"])
    harness.ensure_gitignore(tmp_path, ["aegon.json", "new.txt"])
    lines = (tmp_path / ".gitignore").read_text().split()
    assert lines.count("aegon.json") == 1
    assert "run.json" in lines and "new.txt" in lines
