"""In-memory fakes for the ports — the payoff of the ports/adapters design.

With these, the whole pipeline runs with no SDK, network, terminal or git.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from aegon.agents.roles import AgentRole
from aegon.ports.agent_runner import AgentResult
from aegon.ports.ui import Decision
from aegon.ports.vcs import CommandResult


class FakeUI:
    def __init__(
        self,
        answers: list[str] | None = None,
        decisions: list[Decision] | None = None,
        multiline: list[str] | None = None,
    ) -> None:
        self._answers = deque(answers or [])
        self._decisions = deque(decisions or [])
        self._multiline = deque(multiline or [])
        self.messages: list[str] = []

    def ask(self, prompt: str) -> str:
        return self._answers.popleft() if self._answers else ""

    def read_multiline(self, prompt: str) -> str:
        return self._multiline.popleft() if self._multiline else ""

    def notify(self, message: str) -> None:
        self.messages.append(message)

    def checkpoint(self, question, *, allow_revise=False):
        decision = self._decisions.popleft() if self._decisions else Decision.APPROVE
        return decision, ""

    def open_in_browser(self, path: Path) -> bool:
        return False


class FakeAgentRunner:
    """Returns canned text per role label; records every call."""

    def __init__(self, outputs: dict[str, str]) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, str]] = []

    async def run(self, role: AgentRole, prompt: str, *, cwd=None) -> AgentResult:
        self.calls.append((role.label, prompt))
        for key, text in self._outputs.items():
            if role.label.startswith(key):
                return AgentResult(text=text, cost_usd=0.01)
        return AgentResult(text="", cost_usd=0.0)


class FakeVCS:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def git(self, args, cwd) -> CommandResult:
        self.calls.append(args)
        return CommandResult(0, "")

    def is_repo(self, project) -> bool:
        return True

    def remote_is_empty(self, project) -> bool:
        return False

    def open_pull_request(self, project, repo, base, head, title, body) -> None:
        self.calls.append(["pr", head])
