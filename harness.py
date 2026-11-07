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
import html
import json
import re
import shutil
import subprocess
import sys
import webbrowser
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
    "instructions exists.\n\n"
    "PROGRESS TRACKING: the project contains a progress.md whose '## Tasks' "
    "section lists tasks as checkboxes. Work through the UNCHECKED ('- [ ]') tasks "
    "in order. Immediately after you actually finish a task, use the Edit tool to "
    "change that exact line's '- [ ]' to '- [x]' in progress.md. Only check a task "
    "once its work is genuinely done. Never uncheck an already-checked task.\n\n"
    "When done, report the list of files you created or changed, one per line."
)


# --- small helpers ---------------------------------------------------------
def slugify(text: str) -> str:
    """Turn an idea into a short, filesystem-safe folder name."""
    words = re.sub(r"[^a-z0-9\s-]", "", text.lower()).split()
    slug = "-".join(words[:4]).strip("-")
    return slug or "project"


def ask(prompt: str) -> str:
    return input(prompt).strip()


def read_multiline(prompt: str) -> str:
    """Read a possibly multi-line / pasted instruction until EOF (Ctrl-D).

    A single input() captures only one line, so a pasted multi-line block would
    spill into later prompts. Reading until EOF captures the whole thing.
    """
    print(prompt)
    print("  (enter your instruction — paste is fine — then Ctrl-D on an empty line)")
    lines: list[str] = []
    try:
        while True:
            lines.append(input())
    except EOFError:
        print()  # tidy newline after the Ctrl-D
    return "\n".join(lines).strip()


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
            progress_md = PROJECTS_DIR / name / "progress.md"
            if not progress_md.exists():
                status = "no plan"
            else:
                done, total = plan_progress(progress_md)
                if total == 0:
                    status = "no tasks"
                elif done == 0:
                    status = f"0/{total} tasks  (not started)"
                elif done >= total:
                    status = f"{done}/{total} tasks  (complete)"
                else:
                    status = f"{done}/{total} tasks"
            print(f"  {i}) {name:<20} {status}")
        while True:
            pick = ask("Pick a number: ")
            if pick.isdigit() and 1 <= int(pick) <= len(existing):
                name = existing[int(pick) - 1]
                break
            print("   (enter a valid number)")
        instruction = idea_arg or read_multiline(
            f"What should we work on in '{name}'?")
        return PROJECTS_DIR / name, instruction, False

    # new project
    idea = idea_arg or read_multiline("Describe the app you want to build:")
    suggested = slugify(idea)
    name = ask(f"Project folder name [{suggested}]: ") or suggested
    name = slugify(name)
    path = PROJECTS_DIR / name
    if path.exists():
        print(f"(a project named '{name}' already exists — continuing in it)")
    path.mkdir(parents=True, exist_ok=True)

    # Per-project config: which GitHub repo this project pushes to.
    repo = ask("GitHub repo for this project (git URL, blank to skip): ")
    cfg = {"branch": "main"}
    if repo:
        cfg["github_repo"] = repo
    save_config(path, cfg)
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


def tasks_from_md(progress_md: Path) -> list[tuple[str, bool]]:
    """Read tasks and their checked state from progress.md."""
    tasks = []
    for line in progress_md.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*- \[([ xX])\]\s+(.*)", line)
        if m:
            tasks.append((m.group(2).strip(), m.group(1).lower() == "x"))
    return tasks


def write_plan_html(data: dict, project: Path, idea: str,
                    progress_md: Path | None = None) -> Path:
    """Render the plan as a self-contained, styled HTML file with task checkboxes.

    Task checked-state is read from progress.md when available (so the HTML can
    be refreshed after scaffolding to show progress); otherwise all unchecked.
    """
    esc = html.escape

    if progress_md and progress_md.exists():
        tasks = tasks_from_md(progress_md)
    else:
        tasks = [(str(s), False) for s in data.get("steps") or []]
    done = sum(1 for _, c in tasks if c)
    total = len(tasks)

    file_rows = ""
    for f in data.get("files") or []:
        if isinstance(f, dict):
            file_rows += (f"<tr><td class='path'>{esc(str(f.get('path', '?')))}</td>"
                          f"<td>{esc(str(f.get('purpose', '')))}</td></tr>")
        else:
            file_rows += f"<tr><td class='path'>{esc(str(f))}</td><td></td></tr>"

    task_items = ""
    for text, checked in tasks:
        box = "checked" if checked else ""
        cls = "done" if checked else ""
        task_items += (f"<li class='{cls}'><label><input type='checkbox' disabled "
                       f"{box}> {esc(text)}</label></li>")

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Build Plan</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.6 system-ui, sans-serif; max-width: 760px;
         margin: 2rem auto; padding: 0 16px; }}
  h1 {{ font-size: 1.4rem; margin-bottom: .2rem; }}
  .idea {{ color: #888; margin-bottom: 1.5rem; white-space: pre-wrap; }}
  .k {{ font-weight: 600; }}
  .prog {{ color: #888; font-size: .9rem; margin-bottom: .3rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: .5rem 0 1.5rem; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #8884; vertical-align: top; }}
  .path {{ font-family: ui-monospace, monospace; white-space: nowrap; }}
  ul.tasks {{ list-style: none; padding-left: 0; }}
  ul.tasks li {{ margin: .3rem 0; }}
  ul.tasks li.done label {{ color: #888; text-decoration: line-through; }}
  input[type=checkbox] {{ margin-right: .5rem; }}
  section {{ margin-bottom: 1.5rem; }}
</style></head><body>
<h1>🜂 Build Plan</h1>
<div class="idea">{esc(idea)}</div>
<section><span class="k">Summary:</span> {esc(str(data.get('summary', '—')))}</section>
<section><span class="k">Stack:</span> {esc(str(data.get('stack', '—')))}</section>
<section><div class="k">Files</div><table>{file_rows}</table></section>
<section><div class="k">Tasks</div>
<div class="prog">{done}/{total} done</div>
<ul class="tasks">{task_items}</ul></section>
</body></html>"""

    path = project / "plan.html"
    path.write_text(doc, encoding="utf-8")
    return path


def open_in_browser(path: Path) -> bool:
    """Best-effort open of a local file in the browser (handles WSL)."""
    target = str(path.resolve())
    for opener in ("wslview", "xdg-open"):
        if shutil.which(opener):
            try:
                subprocess.Popen([opener, target],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                pass
    try:
        return webbrowser.open(path.resolve().as_uri())
    except webbrowser.Error:
        return False


def write_progress_md(data: dict, project: Path, idea: str) -> Path:
    """Write progress.md with tasks as checkboxes, for live progress + resuming."""
    idea_line = " ".join(idea.splitlines())
    lines = ["# Build Plan", "", f"> {idea_line}", "",
             f"**Stack:** {data.get('stack', '—')}", "", "## Files", ""]
    for f in data.get("files") or []:
        if isinstance(f, dict):
            lines.append(f"- `{f.get('path', '?')}` — {f.get('purpose', '')}")
        else:
            lines.append(f"- `{f}`")
    lines += ["", "## Tasks", ""]
    for step in data.get("steps") or []:
        lines.append(f"- [ ] {step}")
    lines.append("")
    path = project / "progress.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def extract_tasks(text: str) -> list[str]:
    """Pull bullet / numbered lines out of free-form text to use as tasks."""
    tasks = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:\d+[.)]|[-*])\s+(.+)", line)
        if m:
            tasks.append(m.group(1).strip())
    return tasks


def write_progress_md_fallback(raw: str, project: Path, idea: str) -> Path:
    """Write progress.md from unparseable planner output, so a run is still
    resumable. Any bullet/numbered lines become checkboxes."""
    idea_line = " ".join(idea.splitlines())
    tasks = extract_tasks(raw) or ["Complete the plan described above"]
    lines = ["# Build Plan", "", f"> {idea_line}", "", "## Plan", "",
             raw.strip(), "", "## Tasks", ""]
    lines += [f"- [ ] {t}" for t in tasks]
    lines.append("")
    path = project / "progress.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def plan_progress(plan_md: Path) -> tuple[int, int]:
    """Count (checked, total) task checkboxes in progress.md."""
    text = plan_md.read_text(encoding="utf-8")
    done = len(re.findall(r"- \[x\]", text, flags=re.IGNORECASE))
    todo = len(re.findall(r"- \[ \]", text))
    return done, done + todo


# --- per-project config + git/github --------------------------------------
def config_path(project: Path) -> Path:
    return project / "aegon.json"


def load_config(project: Path) -> dict:
    p = config_path(project)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(project: Path, cfg: dict) -> None:
    config_path(project).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git command in cwd; return (returncode, combined output)."""
    proc = subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def ensure_gitignore(project: Path, entries: list[str]) -> None:
    """Make sure each entry is present in the project's .gitignore."""
    gi = project / ".gitignore"
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    to_add = [e for e in entries if e not in existing]
    if to_add:
        with gi.open("a", encoding="utf-8") as f:
            if existing and existing[-1].strip():
                f.write("\n")
            f.write("\n".join(to_add) + "\n")


def publish(project: Path, idea: str) -> None:
    """Commit the project and push to its configured GitHub repo (if any)."""
    cfg = load_config(project)
    repo = cfg.get("github_repo")
    if not repo:
        print(f"\nno GitHub repo configured — skipping push.")
        print(f"   (add \"github_repo\" to {config_path(project)} to enable it)")
        return

    decision, _ = checkpoint(f"Push this project to {repo} ?")
    if decision != "approve":
        print("skipped push.")
        return

    branch = cfg.get("branch", "main")

    if not (project / ".git").exists():
        run_git(["init"], project)
        run_git(["branch", "-M", branch], project)

    # keep harness-only files out of the app's repo
    ensure_gitignore(project, ["aegon.json", "run.json"])

    # point origin at the configured repo (add or update)
    rc, _ = run_git(["remote", "get-url", "origin"], project)
    run_git(["remote", "set-url" if rc == 0 else "add", "origin", repo], project)

    run_git(["add", "-A"], project)
    default_msg = f"Aegon: build {project.name}"
    msg = ask(f'Commit message [{default_msg}]: ') or default_msg
    rc, out = run_git(["commit", "-m", msg], project)
    if rc != 0 and "nothing to commit" in out:
        print("nothing new to commit.")

    print(f"pushing to {repo} ({branch})…")
    rc, out = run_git(["push", "-u", "origin", branch], project)
    print(f"✓ pushed to {repo} ({branch})." if rc == 0 else f"push failed:\n{out}")


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
    progress_md = project / "progress.md"
    plan_data: dict | None = None

    # --- Resume? existing project with an unfinished progress.md -----------
    resume = False
    if not is_new and progress_md.exists() and "- [ ]" in progress_md.read_text(encoding="utf-8"):
        done, total = plan_progress(progress_md)
        print(f"\nfound an existing plan — {done}/{total} tasks done.")
        resume = ask("Resume it or make a new plan? [r]esume / [n]ew: ").lower()[:1] != "n"

    if resume:
        plan = progress_md.read_text(encoding="utf-8")
        print("resuming progress.md (continuing the unchecked tasks)")
    else:
        context = "" if is_new else (
            "\nThis is an EXISTING project; read its current files before planning."
        )
        # --- Stage 1: PLAN (with optional revise loop) ---------------------
        plan_prompt = f"App / task: {idea}{context}"
        while True:
            plan, cost = await run_agent(
                label="planner", system=PLANNER_SYSTEM, prompt=plan_prompt,
                tools=[], model=PLANNER_MODEL, stream_text=False,
            )
            total_cost += cost
            plan_data = parse_plan(plan)
            # Write the checkbox progress.md right now, during planning, so it
            # always exists (structured if the JSON parsed, else from raw text).
            if plan_data:
                write_progress_md(plan_data, project, idea)
                render_plan(plan_data)               # quick glance in the terminal
                html_path = write_plan_html(plan_data, project, idea, progress_md)
                opened = open_in_browser(html_path)
                print(f"\n   plan: {progress_md}  ·  {html_path}"
                      + ("  (opened)" if opened else ""))
            else:
                write_progress_md_fallback(plan, project, idea)
                print(plan)
                print(f"\n   plan: {progress_md}")
            decision, feedback = checkpoint("Accept this plan?", allow_revise=True)
            if decision == "quit":
                print("\naborted at plan stage. (progress.md was written)")
                return
            if decision == "approve":
                break
            plan_prompt = (
                f"App / task: {idea}{context}\n\nPrevious plan:\n{plan}\n\n"
                f"Revise the plan per this feedback: {feedback}"
            )

        # Hand the checkbox file to the scaffolder to tick off.
        plan = progress_md.read_text(encoding="utf-8")

    # --- Stage 2: SCAFFOLD -------------------------------------------------
    scaffold_prompt = (
        f"App / task: {idea}\n\nBuild plan (tasks are the checkboxes in progress.md):\n"
        f"{plan}\n\nWork through the unchecked tasks now, creating or updating the "
        "files, and tick each task off in progress.md as you complete it."
    )
    report, cost = await run_agent(
        label="scaffolder", system=SCAFFOLDER_SYSTEM, prompt=scaffold_prompt,
        tools=["Write", "Read", "Edit"], model=SCAFFOLDER_MODEL,
        cwd=str(project), permission_mode="acceptEdits",
    )
    total_cost += cost

    if progress_md.exists():
        done, total = plan_progress(progress_md)
        print(f"\n   progress: {done}/{total} tasks checked in {progress_md}")
        # Refresh plan.html so its checkboxes reflect the scaffolder's progress.
        if plan_data:
            write_plan_html(plan_data, project, idea, progress_md)

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
    # --- Stage 3: PUBLISH (commit + push to the project's repo) ------------
    if kept:
        publish(project, idea)

    print("\n" + "─" * 60)
    print(f"done · ${total_cost:.4f} · project: {project}/"
          + ("" if kept else "  (you marked this run as not kept)"))


def main() -> None:
    args = sys.argv[1:]
    idea_arg = ""
    if args and args[0] in ("--file", "-f"):
        if len(args) < 2:
            print("usage: harness.py --file <path>")
            raise SystemExit(1)
        idea_arg = Path(args[1]).read_text(encoding="utf-8").strip()
    elif args:
        idea_arg = " ".join(args)
    asyncio.run(run(idea_arg))


if __name__ == "__main__":
    main()
