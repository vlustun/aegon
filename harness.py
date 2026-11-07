"""
Aegon — Agent Harness (Phase 1: Hello-harness)

What this does
--------------
Takes an app-idea prompt on the command line, hands it to an *orchestrator*
agent, which delegates to a *planner* sub-agent to produce a build plan, then
prints that plan. No files are written and no shell commands run in this phase —
it is purely to watch the orchestrator → sub-agent dispatch work end to end.

Run it:
    .venv/bin/python harness.py "a CLI todo app in Python"

How it maps to the plan (see PLAN.md)
-------------------------------------
- The top-level `query()` call IS the orchestrator.
- `agents={"planner": ...}` defines a sub-agent the orchestrator can call via
  the built-in `Task` tool.
- `allowed_tools=["Task"]` means the orchestrator can ONLY spawn sub-agents —
  it cannot touch the filesystem or run commands. That keeps phase 1 safe.
"""

import asyncio
import sys

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

# Keep the first runs cheap. Bump the orchestrator to "claude-opus-5-5" later
# (see PLAN.md: Opus for orchestration, Sonnet for coding) once it all works.
ORCHESTRATOR_MODEL = "claude-sonnet-5-5"
PLANNER_MODEL = "claude-sonnet-5-5"

# --- The Planner sub-agent ------------------------------------------------
# It has NO tools (tools=[]) — it only reasons and returns text. Its whole job
# is to turn a one-line app idea into a concrete, ordered build plan.
PLANNER = AgentDefinition(
    description="Turns an app idea into a concrete, ordered build plan. Use for any 'plan this app' request.",
    prompt=(
        "You are a software planning specialist. Given an application idea, "
        "produce a concise build plan with:\n"
        "  1. A one-line summary of what the app is.\n"
        "  2. The tech stack (language, key libraries, how it's run).\n"
        "  3. A numbered list of files to create, each with a one-line purpose.\n"
        "  4. An ordered list of build steps.\n"
        "Keep it tight and practical. Do NOT write any code — only the plan."
    ),
    tools=[],          # read-only reasoning; no file or shell access
    model=PLANNER_MODEL,
)

# --- The Orchestrator -----------------------------------------------------
ORCHESTRATOR_SYSTEM = (
    "You are the orchestrator of an app-building harness. "
    "When given an app idea, delegate the planning to the 'planner' sub-agent "
    "(via the Task tool), then present its plan to the user clearly. "
    "In this phase you do not write files or run commands yourself."
)


async def run(prompt: str) -> None:
    options = ClaudeAgentOptions(
        system_prompt=ORCHESTRATOR_SYSTEM,
        agents={"planner": PLANNER},
        allowed_tools=["Task"],      # orchestrator may ONLY spawn sub-agents
        permission_mode="default",
        model=ORCHESTRATOR_MODEL,
        max_turns=8,
    )

    print(f"\n🜂  Aegon — planning: {prompt!r}\n" + "─" * 60)

    # query() is an async generator that streams messages as they arrive.
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
        elif isinstance(message, ResultMessage):
            print("─" * 60)
            cost = message.total_cost_usd
            if cost is not None:
                print(f"done · {message.num_turns} turns · ${cost:.4f}")
            else:
                print(f"done · {message.num_turns} turns")


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: .venv/bin/python harness.py "<your app idea>"')
        raise SystemExit(1)
    prompt = " ".join(sys.argv[1:])
    asyncio.run(run(prompt))


if __name__ == "__main__":
    main()
