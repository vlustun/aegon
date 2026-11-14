"""Central configuration.

A single immutable ``Settings`` object replaces the module-level constants of the
old harness. Passing it explicitly (dependency injection) keeps roles and stages
free of global state and makes per-role models trivial to vary in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- agent system prompts (unchanged wording from the original harness) ------
PLANNER_SYSTEM = (
    "You are a software planning specialist. Given an application idea (and, for "
    "an existing project, its current state), produce a concise build plan.\n"
    "Respond with ONLY a single JSON object (no prose, no code fences) of this shape:\n"
    "{\n"
    '  "summary": "one line on what the app is / what this change does",\n'
    '  "stack":   "language, key libraries, how it is run",\n'
    '  "files":   [{"path": "relative/path", "purpose": "one line"}],\n'
    '  "steps":   ["ordered build step", "..."]\n'
    "}\n"
    "Keep it tight and practical. Do NOT write any code — only the plan JSON."
)

SCAFFOLDER_SYSTEM = (
    "You are a scaffolding specialist. Given a build plan, create or update the "
    "files it lists using the Write/Edit tools, with working starter code — real, "
    "runnable code rather than empty placeholders wherever practical. Use relative "
    "paths (they resolve inside the project folder). You can run shell commands "
    "(e.g. `composer install`, `npm install`, `pip install`) to fetch dependencies "
    "and verify the project builds. For an existing project, first "
    "Read the relevant files and preserve what's there; add or modify rather than "
    "overwrite wholesale. Keep files small and focused. Ensure a README with run "
    "instructions exists.\n\n"
    "PROGRESS TRACKING: the task names a plan checklist file (a Markdown file with "
    "a '## Tasks' section of checkboxes). Work through its UNCHECKED ('- [ ]') "
    "tasks in order. Immediately after you actually finish a task, use the Edit "
    "tool to change that exact line's '- [ ]' to '- [x]' in that same plan file. "
    "Only check a task once its work is genuinely done. Never uncheck an "
    "already-checked task.\n\n"
    "When done, report the list of files you created or changed, one per line."
)

TESTER_SYSTEM = (
    "You are a test runner. Inspect the project to find its test setup (e.g. "
    "pytest, phpunit, npm test, go test, cargo test), install dependencies if "
    "needed, and run the FULL test suite. Do NOT modify any source or test files — "
    "only run things. Then, as the VERY LAST line of your reply, output exactly "
    "'RESULT: PASS' if every test passed, or 'RESULT: FAIL' otherwise. Just above "
    "that line, include the most relevant failing output (or note 'all green' on "
    "success). If there is no test suite at all, output 'RESULT: NONE'."
)

FIXER_SYSTEM = (
    "You are a debugging specialist. You are given failing test output for a "
    "project. Fix the underlying problem by editing the code with the Edit/Write "
    "tools. Prefer fixing the source over changing tests; only change a test if it "
    "is clearly wrong. Keep changes minimal and focused. You may run commands to "
    "check your work. Briefly report what you changed."
)


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for a harness session."""

    projects_dir: Path = Path("projects")

    planner_model: str = "claude-sonnet-5-5"
    scaffolder_model: str = "claude-sonnet-5-5"
    tester_model: str = "claude-sonnet-5-5"
    fixer_model: str = "claude-sonnet-5-5"

    max_fix_attempts: int = 3

    planner_system: str = PLANNER_SYSTEM
    scaffolder_system: str = SCAFFOLDER_SYSTEM
    tester_system: str = TESTER_SYSTEM
    fixer_system: str = FIXER_SYSTEM

    # files the harness keeps out of a built app's repo
    harness_only_files: tuple[str, ...] = ("aegon.json", "run.json")
