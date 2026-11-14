"""The agent-execution port.

Wraps "run one focused sub-agent to completion". The Claude Agent SDK
implementation lives in ``aegon.adapters.sdk_runner``; tests inject a fake that
returns canned output without touching the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aegon.agents.roles import AgentRole


@dataclass(frozen=True)
class AgentResult:
    text: str
    cost_usd: float


class AgentRunner(Protocol):
    async def run(
        self,
        role: AgentRole,
        prompt: str,
        *,
        cwd: str | None = None,
    ) -> AgentResult:
        """Run a single agent (configured by ``role``) against ``prompt``."""
        ...
