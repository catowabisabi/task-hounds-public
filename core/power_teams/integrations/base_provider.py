"""
base_provider.py — Compatibility shim for the backend adapter layer.

The real implementation lives in:
    power_teams.runtime.backend_registry   ← factory
    power_teams.runtime.backends.base      ← BackendAdapter ABC
    power_teams.runtime.backends.opencode  ← OpenCode implementation
    power_teams.runtime.backends.hermes    ← Hermes stub (planned)
    power_teams.runtime.backends.openclaw  ← OpenClaw stub (planned)

This file is kept so existing call sites using get_provider() continue to work.
New code should import directly from backend_registry:

    from power_teams.runtime.backend_registry import get_backend
    adapter = get_backend(agent_row)
    result  = adapter.run(prompt)      # returns JsonResult

BaseProvider is also kept as a thin ABC alias so any external code
subclassing it still works (it now delegates to BackendAdapter).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

# Re-export the real base class so subclasses still resolve
from power_teams.runtime.backends.base import BackendAdapter as BaseProvider  # noqa: F401


def get_provider(
    agent_row: dict,
    stream_file: Path | None = None,
    log_fn: Callable | None = None,
) -> "BaseProvider":
    """
    Compatibility wrapper.  Returns a BackendAdapter instance.

    Prefer calling get_backend() from backend_registry directly in new code.
    """
    from power_teams.runtime.backend_registry import get_backend
    return get_backend(agent_row, stream_file=stream_file, log_fn=log_fn)
