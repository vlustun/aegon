# Aegon

A learning project: an agent harness that takes a prompt and orchestrates
focused sub-agents to build an application. Built on the
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk).

See [PLAN.md](PLAN.md) for the architecture and roadmap.

## Setup

Requires Python 3 with `venv`, Node.js, and the Claude Code CLI (already
installed and authenticated on this machine).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The harness authenticates through the logged-in Claude Code CLI, so no separate
`ANTHROPIC_API_KEY` is required.

## Run (phase 1)

```bash
.venv/bin/python harness.py "a CLI todo app in Python"
```

Phase 1 only produces a build plan — it writes no files and runs no commands.
