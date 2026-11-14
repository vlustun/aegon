"""Aegon — a staged, checkpointed agent harness that builds apps on disk.

The package is organized as a ports-and-adapters (hexagonal) architecture:

    domain/       pure value objects + logic (no I/O)
    ports/        abstractions the core depends on (Protocols)
    adapters/     concrete implementations of the ports (console, SDK, git)
    rendering/    plan renderers (markdown / html / terminal)
    persistence/  repositories for plan files, project config, run log
    agents/       agent-role specs + factory
    services/     project selection + publishing
    pipeline/     Stage abstraction + stages + orchestrator

``aegon.__main__`` is the composition root: it wires concrete adapters into the
orchestrator. ``harness.py`` at the repo root remains a thin shim for back-compat.
"""
