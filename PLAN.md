# Aegon — Agent Harness for Application Creation

A learning project: a harness that takes a single prompt and orchestrates several
focused agents to produce a working application on disk.
---

## Decisions locked in

| Decision | Choice |
|---|---|
| Engine | **Claude Agent SDK** (`claude-agent-sdk`, Python) |
| Language | Python |
| Target apps | Generic (works for web apps, CLIs, backend APIs) |
| Autonomy | Human checkpoints between major phases |

### Why the Claude Agent SDK

The harness needs file tools (read/write/edit), a shell (run `npm install`,
`pytest`, etc.), and sub-agents. The Agent SDK ships all three — it is Claude
Code packaged as a Python library, with a native **subagents** feature that maps
directly onto "separate agents for different actions."

Alternatives considered:
- **Raw Claude API + Tool Runner** — most educational, but we'd hand-write every
  file/bash tool and subagent dispatch. Better as a *second* project.
- **Managed Agents** — Anthropic hosts everything; overkill for a local learning tool.

Caveat: the Agent SDK is a *harness only* — it runs locally, we own deployment.
Fine for a local tool.

---

## Architecture

```
          ┌─────────────────────────────────────────┐
  prompt ─▶│            ORCHESTRATOR                  │
          │  decompose → dispatch → checkpoint → stitch│
          └───────────────┬─────────────────────────┘
                          │ spawns focused sub-agents
        ┌─────────┬───────┼────────┬──────────┐
        ▼         ▼       ▼        ▼          ▼
     Planner  Scaffolder Coder   Tester    Reviewer
     (design)  (files/   (writes  (runs     (reads &
               dirs)     code)    tests)    critiques)
                          │
                          ▼
                  working app on disk  +  run log
```

- **Orchestrator** — top-level loop. Takes the prompt, gets a plan from the
  Planner, dispatches to sub-agents, pauses at human checkpoints, stitches
  results.
- **Sub-agents** — each scoped, with its own context and a restricted tool set.
  The Reviewer, for example, gets *read-only* tools to keep it honest and cheap.
- Each agent returns a structured result; the orchestrator decides the next step.

---

## Key design decisions (defaults)

| Area | Default | Why |
|---|---|---|
| Models | Opus for Orchestrator/Planner, Sonnet for Coder/Tester, Haiku for simple steps | Match cost to difficulty |
| Checkpoints | Pause after **plan**, after **code written**, before **destructive/install** steps | Safe, debuggable |
| Workspace | Each run gets its own dir: `runs/<timestamp>/` | Isolation; easy to inspect or discard |
| State | Write `run.json` logging every step + agent output | See *why* it did what it did |
| Permissions | Bash gated behind approval at first | Watch what it runs while learning |

Model IDs: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`.

---

## Build phases

1. **Hello-harness** — one orchestrator, one sub-agent, prints a plan from the
   prompt. No file writing yet. *Goal: see the SDK loop + subagent dispatch work.*
2. **Scaffold agent** — creates a directory + starter files. First artifact on disk.
3. **Coder + checkpoints** — orchestrator pauses for approval between
   plan → scaffold → code.
4. **Tester + Reviewer** — run the generated app's tests, feed failures back for a
   fix loop.
5. **Polish** — per-agent models, `run.json` log, cost tracking.

Start with phases 1–2, then grow.

---

## Open items / TODO

- [ ] Confirm API access (`ANTHROPIC_API_KEY` or `ant auth login`).
- [ ] Set up project: venv + `pip install claude-agent-sdk`.
- [ ] Build phase 1.
