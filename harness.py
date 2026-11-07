"""
Aegon — Agent Harness (Phase 3 + project selection)

What this does
--------------
On each run it first asks whether you're starting a NEW project or continuing an
EXISTING one:

  • New      → you describe the app; it suggests a folder name slugged from that
               idea (accept or override), then builds in projects/<name>/.
  • Existing → it lists projects/, you pick one and say what to work on next;
               the agents can read the current files and build on top of them.

Then it runs a staged, checkpointed pipeline where your Python code is the
orchestrator:

    plan  →  [checkpoint]  →  scaffold  →  [checkpoint]  →  done

Run it:
    .venv/bin/python harness.py
    .venv/bin/python harness.py "a CLI todo app in Python"   # pre-fills the idea

How it maps to the plan (see PLAN.md)
-------------------------------------
- planner    → tools=[]                      (reasoning only, no disk access)
- scaffolder → tools=["Write","Read","Edit"] (writes/edits files, no shell),
               cwd = the project folder
- Between stages, `checkpoint()` pauses for your approval.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

PROJECTS_DIR = Path("projects")

# Keep runs cheap while learning. See PLAN.md for the intended per-role models.
PLANNER_MODEL = "claude-sonnet-5-5"
SCAFFOLDER_MODEL = "claude-sonnet-5-5"

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
    "paths (they resolve inside the project folder). For an existing project, first "
    "Read the relevant files and preserve what's there; add or modify rather than "
    "overwrite wholesale. Keep files small and focused. Ensure a README with run "
    "instructions exists. When done, report the list of files you created or "
    "changed, one per line."
)


# --- small helpers ---------------------------------------------------------
def slugify(text: str) -> str:
    """Turn an idea into a short, filesystem-safe folder name."""
    words = re.sub(r"[^a-z0-9\s-]", "", text.lower()).split()
    slug = "-".join(words[:4]).strip("-")
    return slug or "project"


def ask(prompt: str) -> str:
    return input(prompt).strip()


def choose_project(idea_arg: str) -> tuple[Path, str, bool]:
    """Interactively pick a new or existing project.

    Returns (project_path, idea_or_instruction, is_new).
    """
    existing = sorted(p.name for p in PROJECTS_DIR.iterdir() if p.is_dir()) \
        if PROJECTS_DIR.is_dir() else []

    mode = ""
    while mode not in ("n", "e"):
        prompt = "New or existing project? [n]ew / [e]xisting: "
        if not existing:
            print("(no existing projects yet — starting fresh)")
            mode = "n"
            break
        mode = ask(prompt).lower()[:1] or "n"

    if mode == "e":
        print("\nExisting projects:")
        for i, name in enumerate(existing, 1):
            print(f"  {i}) {name}")
        while True:
            pick = ask("Pick a number: ")
            if pick.isdigit() and 1 <= int(pick) <= len(existing):
                name = existing[int(pick) - 1]
                break
            print("   (enter a valid number)")
        instruction = idea_arg or ask(f"What should we work on in '{name}'? ")
        return PROJECTS_DIR / name, instruction, False

    # new project
    idea = idea_arg or ask("Describe the app you want to build: ")
    suggested = slugify(idea)
    name = ask(f"Project folder name [{suggested}]: ") or suggested
    name = slugify(name)
    path = PROJECTS_DIR / name
    if path.exists():
        print(f"(a project named '{name}' already exists — continuing in it)")
    path.mkdir(parents=True, exist_ok=True)
    return path, idea, True


# --- running a single agent -----------------------------------------------
async def run_agent(
    *, label: str, system: str, prompt: str, tools: list[str],
    model: str, cwd: str | None = None, permission_mode: str = "default",
    stream_text: bool = True,
) -> tuple[str, float]:
    """Run one focused sub-agent to completion. Returns (text_output, cost_usd).

    stream_text=False collects the output silently (used for the planner, whose
    JSON we render ourselves instead of dumping raw to the terminal).
    """
    options = ClaudeAgentOptions(
        system_prompt=system,
        allowed_tools=tools,
        permission_mode=permission_mode,
        model=model,
        cwd=cwd,
        max_turns=30,
    )
    print(f"\n▶ {label}" + ("" if stream_text else " (thinking…)") + "\n" + "─" * 60)
    collected: list[str] = []
    cost = 0.0
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    if stream_text:
                        print(block.text)
                    collected.append(block.text)
        elif isinstance(message, ResultMessage):
            cost = message.total_cost_usd or 0.0
    return "\n".join(collected), cost


# --- plan parsing + pretty rendering --------------------------------------
def parse_plan(text: str) -> dict | None:
    """Extract the plan JSON from the planner's output; None if unparseable."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def render_plan(data: dict) -> None:
    """Print a structured plan as a clean, scannable block."""
    print("\n╭─ BUILD PLAN " + "─" * 46)
    print(f"│ summary : {data.get('summary', '—')}")
    print(f"│ stack   : {data.get('stack', '—')}")
    files = data.get("files") or []
    print("│ files   :")
    for f in files:
        if isinstance(f, dict):
            print(f"│    • {f.get('path', '?'):<28} {f.get('purpose', '')}")
        else:
            print(f"│    • {f}")
    steps = data.get("steps") or []
    print("│ steps   :")
    for i, step in enumerate(steps, 1):
        print(f"│    {i}. {step}")
    print("╰" + "─" * 59)


# --- the human checkpoint --------------------------------------------------
def checkpoint(question: str, *, allow_revise: bool = False) -> tuple[str, str]:
    """Ask the user to approve/quit (and optionally revise).

    Returns (decision, feedback) where decision is 'approve', 'revise', or 'quit'.
    """
    opts = "[a]pprove / [r]evise / [q]uit" if allow_revise else "[a]pprove / [q]uit"
    while True:
        choice = ask(f"\n⏸  {question}  {opts}: ").lower()
        if choice in ("a", "approve", ""):
            return "approve", ""
        if choice in ("q", "quit"):
            return "quit", ""
        if allow_revise and choice in ("r", "revise"):
            fb = ask("   what should change? ")
            return "revise", fb
        print("   (please answer a" + ("/r" if allow_revise else "") + "/q)")


async def run(idea_arg: str) -> None:
    print("\n🜂  Aegon")
    project, idea, is_new = choose_project(idea_arg)
    kind = "new project" if is_new else "existing project"
    print(f"\n{kind}: {project}/\n→ task: {idea!r}")

    total_cost = 0.0
    context = "" if is_new else (
        "\nThis is an EXISTING project; read its current files before planning."
    )

    # --- Stage 1: PLAN (with optional revise loop) -------------------------
    plan_prompt = f"App / task: {idea}{context}"
    while True:
        plan, cost = await run_agent(
            label="planner", system=PLANNER_SYSTEM, prompt=plan_prompt,
            tools=[], model=PLANNER_MODEL, stream_text=False,
        )
        total_cost += cost
        plan_data = parse_plan(plan)
        if plan_data:
            render_plan(plan_data)
        else:
            # Fallback: couldn't parse JSON, just show what the planner returned.
            print(plan)
        decision, feedback = checkpoint("Accept this plan?", allow_revise=True)
        if decision == "quit":
            print("\naborted at plan stage. no files written.")
            return
        if decision == "approve":
            break
        plan_prompt = (
            f"App / task: {idea}{context}\n\nPrevious plan:\n{plan}\n\n"
            f"Revise the plan per this feedback: {feedback}"
        )

    # --- Stage 2: SCAFFOLD -------------------------------------------------
    scaffold_prompt = (
        f"App / task: {idea}\n\nApproved build plan:\n{plan}\n\n"
        "Create or update all the files for this plan now."
    )
    report, cost = await run_agent(
        label="scaffolder", system=SCAFFOLDER_SYSTEM, prompt=scaffold_prompt,
        tools=["Write", "Read", "Edit"], model=SCAFFOLDER_MODEL,
        cwd=str(project), permission_mode="acceptEdits",
    )
    total_cost += cost

    decision, _ = checkpoint("Scaffold complete. Keep this result?")
    kept = decision == "approve"

    # --- Wrap up -----------------------------------------------------------
    (project / "run.json").write_text(
        json.dumps(
            {"idea": idea, "is_new": is_new, "plan": plan,
             "scaffold_report": report, "kept": kept, "cost_usd": total_cost},
            indent=2,
        )
    )
    print("\n" + "─" * 60)
    print(f"done · ${total_cost:.4f} · project: {project}/"
          + ("" if kept else "  (you marked this run as not kept)"))


def main() -> None:
    idea_arg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    asyncio.run(run(idea_arg))


if __name__ == "__main__":
    main()
