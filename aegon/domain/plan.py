"""Pure domain logic and value objects — no file, network or terminal I/O.

Everything here is a pure function of its arguments (strings in, values out),
which is what makes it directly unit-testable. File reading/writing lives in
``aegon.persistence`` and ``aegon.rendering``; those layers call into here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum


class TestResult(str, Enum):
    """The tester's trailing ``RESULT:`` sentinel."""

    __test__ = False  # not a pytest test class

    PASS = "PASS"
    FAIL = "FAIL"
    NONE = "NONE"


@dataclass(frozen=True)
class Task:
    """A single plan checklist item."""

    text: str
    done: bool


@dataclass(frozen=True)
class Plan:
    """A parsed build plan.

    ``files`` is kept as the planner's raw list (entries may be dicts with
    ``path``/``purpose`` or bare strings) so renderers can reproduce the exact
    historical formatting for each shape.
    """

    summary: str
    stack: str
    files: list
    steps: list[str]
    raw: dict

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        return cls(
            summary=str(data.get("summary", "—")),
            stack=str(data.get("stack", "—")),
            files=list(data.get("files") or []),
            steps=list(data.get("steps") or []),
            raw=data,
        )


def slugify(text: str) -> str:
    """Turn an idea into a short, filesystem-safe folder name."""
    words = re.sub(r"[^a-z0-9\s-]", "", text.lower()).split()
    slug = "-".join(words[:4]).strip("-")
    return slug or "project"


def parse_plan(text: str) -> dict | None:
    """Extract the plan JSON object from the planner's output; None if none."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def parse_tasks(markdown: str) -> list[Task]:
    """Read tasks and their checked state from plan markdown text."""
    tasks: list[Task] = []
    for line in markdown.splitlines():
        m = re.match(r"\s*- \[([ xX])\]\s+(.*)", line)
        if m:
            tasks.append(Task(m.group(2).strip(), m.group(1).lower() == "x"))
    return tasks


def count_progress(markdown: str) -> tuple[int, int]:
    """Count (checked, total) task checkboxes in plan markdown text."""
    done = len(re.findall(r"- \[x\]", markdown, flags=re.IGNORECASE))
    todo = len(re.findall(r"- \[ \]", markdown))
    return done, done + todo


def extract_tasks(text: str) -> list[str]:
    """Pull bullet / numbered lines out of free-form text to use as tasks."""
    tasks: list[str] = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:\d+[.)]|[-*])\s+(.+)", line)
        if m:
            tasks.append(m.group(1).strip())
    return tasks


def read_result(output: str) -> TestResult | None:
    """Read the tester's trailing 'RESULT: PASS|FAIL|NONE' marker (last wins)."""
    result: TestResult | None = None
    for line in output.splitlines():
        s = line.strip().upper()
        if s.startswith("RESULT: PASS"):
            result = TestResult.PASS
        elif s.startswith("RESULT: FAIL"):
            result = TestResult.FAIL
        elif s.startswith("RESULT: NONE"):
            result = TestResult.NONE
    return result
