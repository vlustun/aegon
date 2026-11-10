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

Plans are per-task. The first build keeps its plan as the canonical build plan
(progress.md). Each later task on an existing project gets its own plan under
plans/<slug>-<timestamp>.md, so earlier plans are never overwritten. When you
continue an existing project you can resume any unfinished plan or start a new one.

Then it runs a staged, checkpointed pipeline where your Python code is the
orchestrator:

    plan  →  [checkpoint]  →  scaffold  →  [checkpoint]  →  done

Run it:
    .venv/bin/python harness.py
    .venv/bin/python harness.py "a CLI todo app in Python"   # pre-fills the idea

How it maps to the plan (see PLAN.md)
-------------------------------------
- planner    → tools=[]                      (reasoning only, no disk access)
- scaffolder → tools=["Write","Read","Edit","Bash"] (writes/edits files and can
               run shell, e.g. composer/npm install), cwd = the project folder
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
from datetime import datetime
from pathlib import Path

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

PROJECTS_DIR = Path("projects")

# Keep runs cheap while learning. See PLAN.md for the intended per-role models.
PLANNER_MODEL = "claude-sonnet-5-5"
SCAFFOLDER_MODEL = "claude-sonnet-5-5"
TESTER_MODEL = "claude-sonnet-5-5"
FIXER_MODEL = "claude-sonnet-5-5"
MAX_FIX_ATTEMPTS = 3

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
            print(f"  {i}) {name:<20} {project_status(PROJECTS_DIR / name)}")
        while True:
            pick = ask("Pick a number: ")
            if pick.isdigit() and 1 <= int(pick) <= len(existing):
                name = existing[int(pick) - 1]
                break
            print("   (enter a valid number)")
        # Defer "what should we work on?" to run(): it offers resume first, and
        # only needs an instruction when a new plan is actually being made.
        return PROJECTS_DIR / name, idea_arg, False

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
def _make_bash_confirmer(label: str):
    """Build a can_use_tool callback that prompts in the terminal before any
    Bash command runs. Other tools (Write/Read/Edit) are left to the agent's
    permission_mode, so this only gates shell commands."""
    async def confirm(tool_name: str, tool_input: dict, context):
        if tool_name != "Bash":
            return PermissionResultAllow()
        cmd = tool_input.get("command", "")
        print(f"\n⏸  {label} wants to run a shell command:\n    {cmd}")
        # input() is blocking; run it off the event loop so streaming isn't stalled.
        ans = (await asyncio.to_thread(ask, "   allow? [y]es / [N]o: ")).lower()
        if ans in ("y", "yes"):
            return PermissionResultAllow()
        return PermissionResultDeny(message="User declined to run this command.")
    return confirm


async def run_agent(
    *, label: str, system: str, prompt: str, tools: list[str],
    model: str, cwd: str | None = None, permission_mode: str = "default",
    stream_text: bool = True, max_turns: int = 30, confirm_bash: bool = False,
) -> tuple[str, float]:
    """Run one focused sub-agent to completion. Returns (text_output, cost_usd).

    stream_text=False collects the output silently (used for the planner, whose
    JSON we render ourselves instead of dumping raw to the terminal).

    confirm_bash=True prompts in the terminal before each Bash command runs
    (used by the scaffolder, which may run composer/npm/pip to fetch deps).
    """
    options = ClaudeAgentOptions(
        system_prompt=system,
        allowed_tools=tools,
        permission_mode=permission_mode,
        model=model,
        cwd=cwd,
        max_turns=max_turns,
        can_use_tool=_make_bash_confirmer(label) if confirm_bash else None,
    )
    print(f"\n▶ {label}" + ("" if stream_text else " (thinking…)") + "\n" + "─" * 60)
    collected: list[str] = []
    cost = 0.0
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if stream_text:
                            print(block.text)
                        collected.append(block.text)
            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0.0
    except ResultError as e:
        # A single agent failing (most commonly hitting its max-turns limit)
        # should not nuke the whole pipeline and throw away work already done.
        # Keep whatever it produced and let the caller's checkpoints decide.
        if e.subtype == "error_max_turns":
            print(f"\n⚠  {label} hit its turn limit ({max_turns}) before finishing — "
                  "keeping its partial work. Raise max_turns if this recurs.")
        else:
            reason = e.terminal_reason or e.subtype or "unknown error"
            print(f"\n⚠  {label} ended early ({reason}) — keeping its partial work.")
    except ClaudeSDKError as e:
        print(f"\n⚠  {label} failed: {e} — keeping any partial work.")
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


def write_plan_html(data: dict, out_path: Path, idea: str,
                    progress_md: Path | None = None) -> Path:
    """Render the plan as a self-contained, styled HTML file with task checkboxes.

    `out_path` is the .html file to write. Task checked-state is read from
    `progress_md` when available (so the HTML can be refreshed after scaffolding
    to show progress); otherwise all unchecked.
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path


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


def write_progress_md(data: dict, out_path: Path, idea: str,
                      title: str = "Build Plan") -> Path:
    """Write a checkbox plan file (`out_path`) for live progress + resuming."""
    idea_line = " ".join(idea.splitlines())
    lines = [f"# {title}", "", f"> {idea_line}", "",
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def extract_tasks(text: str) -> list[str]:
    """Pull bullet / numbered lines out of free-form text to use as tasks."""
    tasks = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:\d+[.)]|[-*])\s+(.+)", line)
        if m:
            tasks.append(m.group(1).strip())
    return tasks


def write_progress_md_fallback(raw: str, out_path: Path, idea: str,
                               title: str = "Build Plan") -> Path:
    """Write a plan file (`out_path`) from unparseable planner output, so a run is
    still resumable. Any bullet/numbered lines become checkboxes."""
    idea_line = " ".join(idea.splitlines())
    tasks = extract_tasks(raw) or ["Complete the plan described above"]
    lines = [f"# {title}", "", f"> {idea_line}", "", "## Plan", "",
             raw.strip(), "", "## Tasks", ""]
    lines += [f"- [ ] {t}" for t in tasks]
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def plan_progress(plan_md: Path) -> tuple[int, int]:
    """Count (checked, total) task checkboxes in a plan file."""
    text = plan_md.read_text(encoding="utf-8")
    done = len(re.findall(r"- \[x\]", text, flags=re.IGNORECASE))
    todo = len(re.findall(r"- \[ \]", text))
    return done, done + todo


# --- plan files: one build plan + per-task plans ---------------------------
def build_plan_path(project: Path) -> Path:
    """The canonical build plan (kept at the project root for back-compat)."""
    return project / "progress.md"


def plans_dir(project: Path) -> Path:
    return project / "plans"


def list_task_plans(project: Path) -> list[Path]:
    """Per-task plans, newest first."""
    d = plans_dir(project)
    return sorted(d.glob("*.md"), reverse=True) if d.is_dir() else []


def all_plans(project: Path) -> list[Path]:
    """The build plan (if any) followed by every per-task plan."""
    plans: list[Path] = []
    bp = build_plan_path(project)
    if bp.exists():
        plans.append(bp)
    plans.extend(list_task_plans(project))
    return plans


def plan_label(plan_path: Path, project: Path) -> str:
    """Human-readable name for a plan file in listings."""
    if plan_path == build_plan_path(project):
        return "build plan"
    return plan_path.stem


def new_task_plan_path(project: Path, idea: str) -> Path:
    """A fresh per-task plan file: plans/<slug>-<timestamp>.md."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(idea) if idea else "task"
    return plans_dir(project) / f"{slug}-{stamp}.md"


def html_for(plan_path: Path, project: Path) -> Path:
    """The .html render path for a plan file.

    The build plan keeps the historical `plan.html` name; a per-task plan gets an
    .html sibling next to it.
    """
    if plan_path == build_plan_path(project):
        return project / "plan.html"
    return plan_path.with_suffix(".html")


def project_status(project: Path) -> str:
    """One-line status for the project picker: build-plan progress + task count."""
    tasks_n = len(list_task_plans(project))
    extra = (f"  (+{tasks_n} task plan{'s' if tasks_n != 1 else ''})"
             if tasks_n else "")
    bp = build_plan_path(project)
    if not bp.exists():
        return "no plan" if not tasks_n else f"no build plan{extra}"
    done, total = plan_progress(bp)
    if total == 0:
        base = "no tasks"
    elif done == 0:
        base = f"build 0/{total}  (not started)"
    elif done >= total:
        base = f"build {done}/{total}  (complete)"
    else:
        base = f"build {done}/{total}"
    return base + extra


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


def run_cmd(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run a command in cwd; return (returncode, combined output)."""
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git command in cwd; return (returncode, combined output)."""
    return run_cmd(["git", *args], cwd)


def remote_is_empty(project: Path) -> bool:
    """True only if 'origin' is reachable and has no branches at all.

    Used to decide a one-time bootstrap: we only push the base branch directly
    when we can positively confirm the remote is empty. Any error (unreachable,
    auth) returns False, so we never push to the base branch on a guess.
    """
    rc, out = run_git(["ls-remote", "--heads", "origin"], project)
    return rc == 0 and not out.strip()


def parse_github_slug(repo_url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub git URL (ssh or https), else None."""
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", repo_url.strip())
    return m.group(1) if m else None


def make_branch_name(project: Path, idea: str) -> str:
    """A unique, readable feature-branch name for this build."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    topic = slugify(idea) if idea else project.name
    return f"aegon/{topic}-{stamp}"[:60].rstrip("-")


def open_pull_request(project: Path, repo: str, base: str, head: str,
                      title: str, body: str) -> None:
    """Open a PR (base ← head) via the gh CLI; fall back to a compare URL."""
    slug = parse_github_slug(repo)
    if shutil.which("gh"):
        rc, out = run_cmd(["gh", "pr", "create", "--base", base, "--head", head,
                           "--title", title, "--body", body], project)
        if rc == 0:
            print(f"✓ opened PR: {out.strip().splitlines()[-1]}")
            return
        if "already exists" in out:
            rc2, url = run_cmd(
                ["gh", "pr", "view", head, "--json", "url", "-q", ".url"], project)
            print(f"   (a PR for {head} already exists){': ' + url if rc2 == 0 else ''}")
            return
        print(f"gh pr create failed:\n{out}\n   (falling back to a compare link)")
    if slug:
        print("→ open a PR here:\n"
              f"   https://github.com/{slug}/compare/{base}...{head}?expand=1")
    else:
        print(f"→ open a PR for branch '{head}' into '{base}' on your repo.")


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
    """Commit the build onto a feature branch and open a PR into the base branch.

    We never push app work straight to the base branch (e.g. main):

      • Empty remote → one-time bootstrap: the base branch is created and pushed
        so there is something for later PRs to target.
      • Otherwise    → the build is committed on a fresh `aegon/<topic>-<ts>`
        branch, pushed, and a PR into the base branch is opened (via the gh CLI,
        or a compare URL is printed as a fallback).

    Simplification: the feature branch is cut from the current working tree, so a
    run is assumed to start from a reasonably up-to-date base.
    """
    cfg = load_config(project)
    repo = cfg.get("github_repo")
    if not repo:
        print("\nno GitHub repo configured — skipping publish.")
        print(f"   (add \"github_repo\" to {config_path(project)} to enable it)")
        return

    base = cfg.get("branch", "main")

    decision, _ = checkpoint(f"Commit this build and open a PR on {repo} ?")
    if decision != "approve":
        print("skipped publishing.")
        return

    if not (project / ".git").exists():
        run_git(["init"], project)
        run_git(["branch", "-M", base], project)

    # keep harness-only files out of the app's repo
    ensure_gitignore(project, ["aegon.json", "run.json"])

    # point origin at the configured repo (add or update)
    rc, _ = run_git(["remote", "get-url", "origin"], project)
    run_git(["remote", "set-url" if rc == 0 else "add", "origin", repo], project)

    # --- Bootstrap an empty remote: create the base branch once --------------
    if remote_is_empty(project):
        print(f"\n(new repo — initializing '{base}' on {repo})")
        run_git(["checkout", base], project)  # best-effort; we created it above
        run_git(["add", "-A"], project)
        default_msg = f"Aegon: initialize {project.name}"
        msg = ask(f'Commit message [{default_msg}]: ') or default_msg
        rc, out = run_git(["commit", "-m", msg], project)
        if rc != 0 and "nothing to commit" in out:
            print("nothing to commit.")
        print(f"pushing initial '{base}'…")
        rc, out = run_git(["push", "-u", "origin", base], project)
        print(f"✓ initialized {repo} ({base}). Future builds will open PRs."
              if rc == 0 else f"push failed:\n{out}")
        return

    # --- Normal path: feature branch + pull request --------------------------
    head = make_branch_name(project, idea)
    run_git(["checkout", "-b", head], project)
    run_git(["add", "-A"], project)
    default_msg = f"Aegon: build {project.name}"
    msg = ask(f'Commit message [{default_msg}]: ') or default_msg
    rc, out = run_git(["commit", "-m", msg], project)
    if rc != 0 and "nothing to commit" in out:
        print("nothing new to commit — skipping PR.")
        run_git(["checkout", base], project)
        return

    print(f"pushing branch '{head}'…")
    rc, out = run_git(["push", "-u", "origin", head], project)
    if rc != 0:
        print(f"push failed:\n{out}")
        return

    body = f"Built by Aegon.\n\nTask: {idea}\n" if idea else "Built by Aegon.\n"
    open_pull_request(project, repo, base, head, msg, body)


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


# --- test + fix loop -------------------------------------------------------
def read_result(output: str) -> str | None:
    """Read the tester's trailing 'RESULT: PASS|FAIL|NONE' marker."""
    result = None
    for line in output.splitlines():
        s = line.strip().upper()
        if s.startswith("RESULT: PASS"):
            result = "PASS"
        elif s.startswith("RESULT: FAIL"):
            result = "FAIL"
        elif s.startswith("RESULT: NONE"):
            result = "NONE"
    return result


async def test_and_fix(project: Path, idea: str) -> tuple[str | None, float]:
    """Run the test suite and, on failure, loop Tester↔Fixer up to a limit.

    Returns (result, cost) where result is 'PASS', 'FAIL', 'NONE', or None
    (skipped). Runs shell commands, so it is gated behind a confirmation.
    """
    decision, _ = checkpoint(
        "Run the test suite? (this executes shell commands in the project)")
    if decision != "approve":
        print("skipped testing.")
        return None, 0.0

    total = 0.0
    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        out, cost = await run_agent(
            label=f"tester (attempt {attempt}/{MAX_FIX_ATTEMPTS})",
            system=TESTER_SYSTEM,
            prompt="Run the project's full test suite and end with the RESULT line.",
            tools=["Bash", "Read"], model=TESTER_MODEL, cwd=str(project),
            permission_mode="bypassPermissions", max_turns=40,
        )
        total += cost
        result = read_result(out)

        if result == "PASS":
            print(f"\n✓ tests pass (attempt {attempt}).")
            return "PASS", total
        if result == "NONE":
            print("\nno test suite found — nothing to run.")
            return "NONE", total

        print(f"\n✗ tests failing (attempt {attempt}).")
        if attempt == MAX_FIX_ATTEMPTS:
            break
        print("   → handing the failures to the fixer…")
        _, cost = await run_agent(
            label=f"fixer (attempt {attempt}/{MAX_FIX_ATTEMPTS})",
            system=FIXER_SYSTEM,
            prompt=f"App / task: {idea}\n\nFailing test output:\n\n{out}\n\n"
                   "Fix the code so the tests pass.",
            tools=["Read", "Edit", "Write", "Bash"], model=FIXER_MODEL,
            cwd=str(project), permission_mode="bypassPermissions", max_turns=40,
        )
        total += cost

    print("\ntests still failing after max attempts — leaving the code to inspect.")
    return "FAIL", total


async def run(idea_arg: str) -> None:
    print("\n🜂  Aegon")
    project, idea, is_new = choose_project(idea_arg)
    kind = "new project" if is_new else "existing project"

    total_cost = 0.0
    plan_data: dict | None = None

    # --- Choose the plan file for this run ---------------------------------
    # The build plan (progress.md) is canonical and never overwritten by a task.
    # Each new task on an existing project gets its own plans/<slug>-<ts>.md, so
    # the original build plan and earlier task plans stay intact.
    user_plan_md = project / "plan.md"
    resume = False
    plan_path: Path | None = None

    if is_new:
        plan_path = build_plan_path(project)          # the canonical build plan
    else:
        unfinished = [p for p in all_plans(project)
                      if "- [ ]" in p.read_text(encoding="utf-8")]
        if unfinished:
            print("\nUnfinished plans:")
            for i, p in enumerate(unfinished, 1):
                done, total = plan_progress(p)
                print(f"  {i}) {plan_label(p, project):<28} {done}/{total} tasks")
            print("  n) start a new task plan")
            while True:
                pick = ask("Resume which? [number] / [n]ew: ").lower()
                if pick[:1] == "n":
                    break
                if pick.isdigit() and 1 <= int(pick) <= len(unfinished):
                    plan_path = unfinished[int(pick) - 1]
                    resume = True
                    break
                print("   (enter a valid number or 'n')")
        # else: nothing to resume → a new task plan (path set once we have idea).

    # A fresh task needs an instruction; a resume does not.
    if not resume and not idea:
        prompt = ("Describe the app you want to build:" if is_new
                  else f"What should we work on in '{project.name}'?")
        idea = read_multiline(prompt)

    # Finalize a new-task plan path now that the idea is known.
    if plan_path is None:
        plan_path = new_task_plan_path(project, idea)

    is_build_plan = plan_path == build_plan_path(project)
    plan_title = "Build Plan" if is_build_plan else "Task Plan"
    html_path = html_for(plan_path, project)
    rel_plan = plan_path.relative_to(project)

    print(f"\n{kind}: {project}/")
    if idea:
        print(f"→ task: {idea!r}")
    print(f"→ plan file: {rel_plan}")

    # --- Stage 1: PLAN (or resume / use a user-supplied plan) --------------
    if resume:
        plan = plan_path.read_text(encoding="utf-8")
        print(f"resuming {rel_plan} (continuing the unchecked tasks)")
    elif is_build_plan and user_plan_md.exists():
        # A plan.md you placed in the project is treated as YOUR build plan: the
        # planner is skipped and plan.md is never overwritten; the checkbox file
        # is derived from it so tasks can be ticked.
        plan = user_plan_md.read_text(encoding="utf-8")
        print(f"using your {user_plan_md} as the plan (it will not be overwritten)")
        if not plan_path.exists():
            write_progress_md_fallback(plan, plan_path, idea, title=plan_title)
            print(f"   (created {rel_plan} to track task progress)")
        else:
            print(f"   (keeping existing {rel_plan} for progress tracking)")
    else:
        context = "" if is_new else (
            "\nThis is an EXISTING project; read its current files before planning."
        )
        # For an existing project the planner gets read-only access to the
        # project folder (cwd = the project) so it plans/answers from the real
        # files, not guesswork. A new project has nothing to read yet.
        planner_tools = [] if is_new else ["Read", "Glob", "Grep"]
        planner_cwd = None if is_new else str(project)
        plan_prompt = f"App / task: {idea}{context}"
        while True:
            plan, cost = await run_agent(
                label="planner", system=PLANNER_SYSTEM, prompt=plan_prompt,
                tools=planner_tools, cwd=planner_cwd,
                model=PLANNER_MODEL, stream_text=False,
            )
            total_cost += cost
            plan_data = parse_plan(plan)
            # Write the checkbox plan file now, during planning, so it always
            # exists (structured if the JSON parsed, else from raw text).
            if plan_data:
                write_progress_md(plan_data, plan_path, idea, title=plan_title)
                render_plan(plan_data)               # quick glance in the terminal
                html_path = write_plan_html(plan_data, html_path, idea, plan_path)
                opened = open_in_browser(html_path)
                print(f"\n   plan: {rel_plan}  ·  {html_path.name}"
                      + ("  (opened)" if opened else ""))
            else:
                write_progress_md_fallback(plan, plan_path, idea, title=plan_title)
                print(plan)
                print(f"\n   plan: {rel_plan}")
            decision, feedback = checkpoint("Accept this plan?", allow_revise=True)
            if decision == "quit":
                print(f"\naborted at plan stage. ({rel_plan} was written)")
                return
            if decision == "approve":
                break
            plan_prompt = (
                f"App / task: {idea}{context}\n\nPrevious plan:\n{plan}\n\n"
                f"Revise the plan per this feedback: {feedback}"
            )

        # Hand the checkbox file to the scaffolder to tick off.
        plan = plan_path.read_text(encoding="utf-8")

    # --- Stage 2: SCAFFOLD -------------------------------------------------
    scaffold_prompt = (
        f"App / task: {idea}\n\nPlan checklist file: {rel_plan}\n"
        f"Plan contents:\n{plan}\n\nWork through the unchecked ('- [ ]') tasks now, "
        f"creating or updating the files, and tick each task off in {rel_plan} as "
        "you complete it."
    )
    report, cost = await run_agent(
        label="scaffolder", system=SCAFFOLDER_SYSTEM, prompt=scaffold_prompt,
        # Bash is allowlisted, so composer/npm/pip etc. run without prompting.
        tools=["Write", "Read", "Edit", "Bash"], model=SCAFFOLDER_MODEL,
        cwd=str(project), permission_mode="acceptEdits", max_turns=80,
    )
    total_cost += cost

    if plan_path.exists():
        done, total = plan_progress(plan_path)
        print(f"\n   progress: {done}/{total} tasks checked in {rel_plan}")
        # Refresh the plan HTML so its checkboxes reflect the scaffolder's progress.
        if plan_data:
            write_plan_html(plan_data, html_path, idea, plan_path)

    # --- Stage 3: TEST + FIX ----------------------------------------------
    test_result, tcost = await test_and_fix(project, idea)
    total_cost += tcost

    decision, _ = checkpoint("All done. Keep this result?")
    kept = decision == "approve"

    # --- Wrap up -----------------------------------------------------------
    (project / "run.json").write_text(
        json.dumps(
            {"idea": idea, "is_new": is_new, "plan_file": str(rel_plan),
             "resumed": resume, "plan": plan, "scaffold_report": report,
             "test_result": test_result, "kept": kept, "cost_usd": total_cost},
            indent=2,
        )
    )
    # --- Stage 4: PUBLISH (commit + push to the project's repo) ------------
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
