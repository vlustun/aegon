"""Stage abstraction and the context passed between stages.

A ``Stage`` is a Strategy with a uniform ``run(ctx)`` interface; the orchestrator
sequences a list of them. Adding a new stage (e.g. a Reviewer) is a new class
appended to the list — no existing stage or the orchestrator changes (OCP).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from aegon.domain.plan import Plan, TestResult


class PipelineAbort(Exception):
    """Raised by a stage to stop the pipeline cleanly (e.g. user quit)."""


@dataclass
class RunContext:
    """Mutable state threaded through the pipeline stages."""

    project: Path
    idea: str
    is_new: bool
    plan_path: Path
    html_path: Path
    rel_plan: Path
    resume: bool
    is_build_plan: bool
    plan_title: str

    plan_text: str = ""
    plan_data: Plan | None = None
    total_cost: float = 0.0
    scaffold_report: str = ""
    test_result: TestResult | None = None
    kept: bool = False

    def add_cost(self, cost: float) -> None:
        self.total_cost += cost


class Stage(ABC):
    name: str = "stage"

    @abstractmethod
    async def run(self, ctx: RunContext) -> None:
        """Advance the run by mutating ``ctx``; raise PipelineAbort to stop."""
        raise NotImplementedError
