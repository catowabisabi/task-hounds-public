"""
openclaw.py — BackendAdapter stub for OpenClaw (Anthropic Claude API).

Status: PLANNED — not yet implemented.

OpenClaw provides an opencode-compatible interface for Anthropic Claude models
(Sonnet, Opus, Haiku).  Allows using Claude as a drop-in agent backend
without running a local opencode serve process.

Config fields (backend_config_json):
    api_key str     Anthropic API key (or set ANTHROPIC_API_KEY env var)
    model   str     e.g. "claude-sonnet-4-5", "claude-opus-4", "claude-haiku-4"

To implement:
    1. Replace NotImplementedError bodies with Anthropic SDK calls
    2. Register in backend_registry.py:
           if backend == "openclaw":
               from power_teams.runtime.backends.openclaw import OpenClawAdapter
               return OpenClawAdapter(agent_row, ...)
    3. Set backend_type = 'openclaw' on the agent in the DB
"""
from __future__ import annotations

from typing import Callable

from power_teams.runtime.backends.base import BackendAdapter
from power_teams.runtime import result_schema as rs


class OpenClawAdapter(BackendAdapter):
    """Anthropic Claude API backend adapter (not yet implemented)."""

    BACKEND = "openclaw"

    def __init__(self, agent_row: dict, *, stream_file=None, log_fn=None):
        self._agent_name = agent_row.get("name", "agent")
        import json as _json
        cfg_raw = agent_row.get("backend_config_json") or "{}"
        try:
            self._cfg = _json.loads(cfg_raw) if isinstance(cfg_raw, str) else (cfg_raw or {})
        except Exception:
            self._cfg = {}
        self._api_key = self._cfg.get("api_key") or ""
        self._model   = agent_row.get("model") or self._cfg.get("model", "claude-sonnet-4-5")

    @property
    def backend_name(self) -> str:
        return self.BACKEND

    @property
    def agent_name(self) -> str:
        return self._agent_name

    def _not_implemented(self, method: str) -> dict:
        return rs.err(
            backend=self.BACKEND,
            agent=self._agent_name,
            error_type="NotImplementedError",
            message=f"OpenClawAdapter.{method}() is not yet implemented. "
                    f"See runtime/backends/openclaw.py to add it.",
            retryable=False,
        )

    def start(self) -> dict:
        # No local process to start — API is always "running"
        return rs.ok(
            backend=self.BACKEND, agent=self._agent_name,
            status="already_running",
            text="Anthropic API requires no local server",
        )

    def stop(self) -> dict:
        return rs.ok(
            backend=self.BACKEND, agent=self._agent_name,
            status=rs.STATUS_STOPPED,
            text="Anthropic API requires no local server to stop",
        )

    def health(self) -> dict:
        return self._not_implemented("health")

    def run(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        on_chunk: Callable[[str], None] | None = None,
        timeout: int = 300,
    ) -> dict:
        return self._not_implemented("run")

    def logs(self, tail: int = 100) -> dict:
        return self._not_implemented("logs")
