"""Claude Agent SDK implementation of the ``AgentRunner`` port.

This is the only module that imports the SDK, so the rest of the harness is
decoupled from it (DIP). It also contains the in-agent failure containment: a
single sub-agent hitting its turn limit keeps its partial work instead of
nuking the pipeline.
"""

from __future__ import annotations

import asyncio

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    query,
)
from claude_agent_sdk._errors import ClaudeSDKError, ResultError

from aegon.agents.roles import AgentRole
from aegon.ports.agent_runner import AgentResult
from aegon.ports.ui import UserInterface


class SdkAgentRunner:
    """Runs one focused sub-agent to completion via the Claude Agent SDK."""

    def __init__(self, ui: UserInterface) -> None:
        self._ui = ui

    def _make_bash_confirmer(self, label: str):
        """Build a can_use_tool callback that prompts before any Bash command.

        Other tools (Write/Read/Edit) are left to the agent's permission_mode, so
        this only gates shell commands.
        """

        async def confirm(tool_name: str, tool_input: dict, context):
            if tool_name != "Bash":
                return PermissionResultAllow()
            cmd = tool_input.get("command", "")
            self._ui.notify(f"\n⏸  {label} wants to run a shell command:\n    {cmd}")
            # input() is blocking; run it off the event loop so streaming isn't stalled.
            ans = (
                await asyncio.to_thread(self._ui.ask, "   allow? [y]es / [N]o: ")
            ).lower()
            if ans in ("y", "yes"):
                return PermissionResultAllow()
            return PermissionResultDeny(message="User declined to run this command.")

        return confirm

    async def run(
        self, role: AgentRole, prompt: str, *, cwd: str | None = None
    ) -> AgentResult:
        options = ClaudeAgentOptions(
            system_prompt=role.system,
            allowed_tools=role.tools,
            permission_mode=role.permission_mode,
            model=role.model,
            cwd=cwd,
            max_turns=role.max_turns,
            can_use_tool=(
                self._make_bash_confirmer(role.label) if role.confirm_bash else None
            ),
        )
        self._ui.notify(
            f"\n▶ {role.label}"
            + ("" if role.stream_text else " (thinking…)")
            + "\n"
            + "─" * 60
        )
        collected: list[str] = []
        cost = 0.0
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            if role.stream_text:
                                self._ui.notify(block.text)
                            collected.append(block.text)
                elif isinstance(message, ResultMessage):
                    cost = message.total_cost_usd or 0.0
        except ResultError as e:
            # A single agent failing (most commonly hitting its max-turns limit)
            # should not nuke the whole pipeline and throw away work already done.
            if e.subtype == "error_max_turns":
                self._ui.notify(
                    f"\n⚠  {role.label} hit its turn limit ({role.max_turns}) before "
                    "finishing — keeping its partial work. Raise max_turns if this recurs."
                )
            else:
                reason = e.terminal_reason or e.subtype or "unknown error"
                self._ui.notify(
                    f"\n⚠  {role.label} ended early ({reason}) — keeping its partial work."
                )
        except ClaudeSDKError as e:
            self._ui.notify(f"\n⚠  {role.label} failed: {e} — keeping any partial work.")
        return AgentResult(text="\n".join(collected), cost_usd=cost)
