"""
base.py — Abstract base class for all backend adapters.

Each backend (opencode, openclaw, hermes, …) implements this interface.
All methods return a JsonResult dict (see result_schema.py).

Layer diagram:
    UI / runner.py
        ↓
    backend_registry.get_backend(agent_row)
        ↓
    BackendAdapter  ← you are here
        ↓
    [OpenCodeAdapter]  [OpenClawAdapter]  [HermesAdapter]  …
        ↓
    underlying process / CLI / HTTP API

Adding a new backend:
    1. Create  runtime/backends/mybackend.py  implementing BackendAdapter
    2. Register it in  runtime/backend_registry.py
    3. Set  backend_type = 'mybackend'  on the agent row in the DB
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class BackendAdapter(ABC):
    """
    Minimal interface every backend must implement.

    Every method returns a JsonResult dict (see result_schema.py):
        {"ok": bool, "backend": str, "agent": str, "run_id": str,
         "status": str, "output": dict | None, "error": dict | None}
    """

    # ── Lifecycle ───────────────────────────────────────────────────────────

    @abstractmethod
    def start(self) -> dict:
        """
        Ensure the backend server / process is running.
        Idempotent — safe to call when already running.

        Returns JsonResult with status="started" or status="already_running".
        """

    @abstractmethod
    def stop(self) -> dict:
        """
        Gracefully stop the backend server / process for this agent.

        Returns JsonResult with status="stopped".
        """

    @abstractmethod
    def health(self) -> dict:
        """
        Check if the backend is reachable and ready.

        Returns JsonResult with status="healthy" or "unhealthy".
        Output may contain {"port": int, "pid": int, "uptime_s": float}.
        """

    # ── Core execution ──────────────────────────────────────────────────────

    @abstractmethod
    def run(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        on_chunk: Callable[[str], None] | None = None,
        timeout: int = 300,
    ) -> dict:
        """
        Send a prompt to the agent and return the full response.

        Args:
            prompt:     The text to send.
            session_id: Reuse an existing session (optional).
            on_chunk:   Called with each streamed text chunk (optional).
            timeout:    Max seconds to wait for a response.

        Returns:
            JsonResult with output["text"] containing the full reply.
        """

    # ── Observability ───────────────────────────────────────────────────────

    @abstractmethod
    def logs(self, tail: int = 100) -> dict:
        """
        Return recent log lines from this backend.

        Returns JsonResult with output["text"] containing the log tail.
        """

    # ── Helpers available to all subclasses ─────────────────────────────────

    @property
    def backend_name(self) -> str:
        """Override in subclass to return e.g. 'opencode'."""
        return self.__class__.__name__.lower().replace("adapter", "")

    @property
    def agent_name(self) -> str:
        """Override or set self._agent_name in __init__."""
        return getattr(self, "_agent_name", "unknown")
