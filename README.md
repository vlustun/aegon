Architecture note · Agent harness

# 🜂 Aegon

A single-prompt harness that orchestrates focused sub-agents to build a working application on disk. Here is how it manages state, recovers from failure between hand-offs, and puts a human in the loop.

---

## The shape

Python code is the orchestrator. Instead of handing one large agent the whole job, Aegon runs a fixed, staged pipeline and spawns a fresh, narrowly-scoped sub-agent for each stage — each with its own system prompt, model, and restricted tool set.

The one idea everything rests on is that nearly all state lives on disk as human-readable files. That single choice makes hand-offs, recovery, and human review three variations on the same thing: the filesystem is the shared memory, and both agents and humans read and write it between stages.

## 01 State management

State is files, not memory. The most important of them is also the work queue and the progress ledger at once.

### `progress.md` is the real state object

The plan isn't just rendered text — it's written out as a Markdown checklist of `- [ ]` / `- [x]` task boxes. This one file is simultaneously the plan, the work queue, and the progress ledger. The scaffolder is instructed to tick a box *immediately* after finishing each task, so completion is persisted continuously rather than all at the end.

---

## 02 Failure recovery between hand-offs

Two layers: contain a single agent's failure so it never discards work, and let a whole run resume from where it stopped.

In-agent containment

A sub-agent failing must not nuke the pipeline. `run_agent` catches `ResultError`/`ClaudeSDKError` — notably `error_max_turns` — keeps whatever partial work reached disk, and returns normally so the next checkpoint can decide. A planner that runs out of turns still leaves a usable `progress.md`.

Resume across runs strongest guarantee

Because state *is* the on-disk checklist, a crashed, quit, or partial run is just a `progress.md` with unchecked boxes. The next run detects remaining `- [ ]` tasks and offers to resume — re-feeding the same checklist so the scaffolder continues the unchecked items. Recovery falls out of the state model for free; there is no separate mechanism.

### The one place with active retry: test ⇄ fix

The tester runs the suite and emits a sentinel last line. On failure the output is handed to a fixer agent; this repeats up to a bound, then gives up and leaves the code for inspection rather than looping forever.

**tester** → suite → RESULT: PASS | FAIL | NONE │ ├─ PASS / NONE → **done** └─ FAIL → **fixer** gets the failing output → edits code ↑\_\_\_\_\_\_\_\_\_\_\_ repeat, max 3 attempts \_\_\_\_\_\_\_\_\_\_\_│ then stop, leave code to inspect

---

## 03 Human-in-the-loop checkpoints

Two distinct mechanisms, deliberately kept separate: coarse gates at phase boundaries, and fine gating on individual shell commands.

### Phase gates

A blocking terminal prompt between major stages returning `approve / revise / quit`, placed at exactly the high-leverage boundaries:

After the plan — with a revise loop

You give feedback; the planner re-plans with the previous plan plus your note as context; repeat until you approve.

Before running tests

Because that stage executes shell commands in the project.

Before keeping the result · before pushing to GitHub

The two outward-facing, hard-to-undo actions each sit behind their own gate.

### Per-command gating

A finer-grained `can_use_tool` callback can prompt before *each individual Bash command*, surfacing the exact command for y/N approval. It runs the blocking prompt off the event loop so the agent's streaming output isn't stalled while waiting on the human.

The trust model in practice

The scaffolder runs with edits auto-accepted and Bash allow-listed, so dependency installs don't nag mid-build. Tester and fixer run with permissions bypassed *but* sit behind a single “Run the test suite?” gate. So the real posture is coarse-grained consent at the dangerous boundary, with the per-command machinery held in reserve for the stricter learning mode.

---

## Honest edges

Where the design is pragmatic rather than bulletproof — worth naming plainly.

Contract

The planner → scaffolder hand-off is a loosely-validated JSON blob regex-extracted from model output, with a text fallback when it doesn't parse. Robust-ish, not a strict schema.

Rollback

“Keep partial work” is graceful degradation, not a transaction. There's no undo of a half-written file beyond re-running.

Models

Every role currently runs on one model to keep learning runs cheap; the per-role model split (Opus to plan, Sonnet to build) is described in the plan but not yet wired in.

Source: harness.py · README.md · PLAN.md · a learning project built on the Claude Agent SDK
