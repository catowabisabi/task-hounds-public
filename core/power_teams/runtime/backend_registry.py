"""
backend_registry.py — Factory for BackendAdapter instances.

Usage:
    from power_teams.runtime.backend_registry import get_backend

    adapter = get_backend(agent_row)          # uses agent_row["backend_type"]
    result  = adapter.run(prompt)             # always returns JsonResult
    if result["ok"]:
        print(result["output"]["text"])
    else:
        print(result["error"]["message"])

Registered backends
───────────────────
    "opencode"  →  OpenCodeAdapter   (default, production-ready)
    "hermes"    →  HermesAdapter     (planned — local LLM)
    "openclaw"  →  OpenClawAdapter   (planned — Anthropic Claude API)

Adding a new backend
────────────────────
    1. Create  src/power_teams/runtime/backends/mybackend.py
       implementing BackendAdapter (see base.py)
    2. Add an entry in the registry dict below
    3. Set backend_type = 'mybackend' on the agent row in the DB
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from power_teams.runtime.backends.base import BackendAdapter


# ── Registry ────────────────────────────────────────────────────────────────
# Maps backend_type string → (module_path, class_name)
# Lazy-loaded so unused backends don't add import cost.

_REGISTRY: dict[str, tuple[str, str]] = {
    "opencode": (
        "power_teams.runtime.backends.opencode",
        "OpenCodeAdapter",
    ),
    "hermes": (
        "power_teams.runtime.backends.hermes",
        "HermesAdapter",
    ),
    "openclaw": (
        "power_teams.runtime.backends.openclaw",
        "OpenClawAdapter",
    ),
}


def get_backend(
    agent_row: dict,
    *,
    stream_file: Path | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> BackendAdapter:
    """
    Return a BackendAdapter instance for the given agent row.

    agent_row must contain at minimum:
        name            agent identifier
        backend_type    which adapter to use (default: "opencode")
        host, port      where the backend serve is running
        model           optional model override
        opencode_agent  agent persona (opencode-specific)
        backend_config_json  JSON string with adapter-specific settings

    Raises:
        ValueError  if backend_type is unknown
    """
    backend = (agent_row.get("backend_type") or "opencode").lower().strip()

    entry = _REGISTRY.get(backend)
    if entry is None:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown backend_type '{backend}'. "
            f"Known backends: {known}. "
            f"To add a new backend implement BackendAdapter and register it in backend_registry.py."
        )

    module_path, class_name = entry
    import importlib
    module = importlib.import_module(module_path)
    cls: type[BackendAdapter] = getattr(module, class_name)
    return cls(agent_row, stream_file=stream_file, log_fn=log_fn)


def list_backends() -> list[str]:
    """Return the names of all registered backends."""
    return sorted(_REGISTRY)


def is_registered(backend_type: str) -> bool:
    """Return True if backend_type is in the registry."""
    return backend_type.lower().strip() in _REGISTRY
