"""Agent roles: the configuration that distinguishes one sub-agent from another.

An ``AgentRole`` is a Strategy for the agent runner — it carries the system
prompt, model, tool set and execution limits. ``AgentRoleFactory`` builds the
concrete roles from ``Settings`` so model/prompt choices live in one place and
the pipeline never hard-codes them (OCP: a new role is a new factory method).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aegon.config import Settings


@dataclass(frozen=True)
class AgentRole:
    label: str
    system: str
    model: str
    tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"
    max_turns: int = 30
    stream_text: bool = True
    confirm_bash: bool = False


class AgentRoleFactory:
    """Builds configured roles from settings."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def planner(self, *, is_new: bool) -> AgentRole:
        # New project: nothing on disk to read, so no tools. Existing project:
        # read-only access so the plan reflects the real files.
        tools = [] if is_new else ["Read", "Glob", "Grep"]
        return AgentRole(
            label="planner",
            system=self._s.planner_system,
            model=self._s.planner_model,
            tools=tools,
            stream_text=False,
        )

    def scaffolder(self) -> AgentRole:
        return AgentRole(
            label="scaffolder",
            system=self._s.scaffolder_system,
            model=self._s.scaffolder_model,
            tools=["Write", "Read", "Edit", "Bash"],
            permission_mode="acceptEdits",
            max_turns=80,
        )

    def tester(self, label: str) -> AgentRole:
        return AgentRole(
            label=label,
            system=self._s.tester_system,
            model=self._s.tester_model,
            tools=["Bash", "Read"],
            permission_mode="bypassPermissions",
            max_turns=40,
        )

    def fixer(self, label: str) -> AgentRole:
        return AgentRole(
            label=label,
            system=self._s.fixer_system,
            model=self._s.fixer_model,
            tools=["Read", "Edit", "Write", "Bash"],
            permission_mode="bypassPermissions",
            max_turns=40,
        )
