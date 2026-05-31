"""
hermes.py — BackendAdapter stub for Hermes (local-first LLM runtime).

Status: PLANNED — not yet implemented.

Hermes is a local-first LLM runtime compatible with llama.cpp / Ollama.
Useful for offline / cost-free agent runs.

Config fields (backend_config_json):
    host    str     default "127.0.0.1"
    port    int     default 11434
    model   str     e.g. "hermes3-llama3.1-8b"

To implement:
    1. Replace NotImplementedError bodies with real HTTP calls to the Hermes API
    2. Register in backend_registry.py:
           if backend == "hermes":
               from power_teams.runtime.backends.hermes import HermesAdapter
               return HermesAdapter(agent_row, ...)
    3. Set backend_type = 'hermes' on the agent in the DB
"""
from __future__ import annotations

from typing import Callable

from power_teams.runtime.backends.base import BackendAdapter
from power_teams.runtime import result_schema as rs


class HermesAdapter(BackendAdapter):
    """Hermes local-LLM backend adapter (not yet implemented)."""

    BACKEND = "hermes"

    def __init__(self, agent_row: dict, *, stream_file=None, log_fn=None):
        self._agent_name = agent_row.get("name", "agent")
        import json as _json
        cfg_raw = agent_row.get("backend_config_json") or "{}"
        try:
            self._cfg = _json.loads(cfg_raw) if isinstance(cfg_raw, str) else (cfg_raw or {})
        except Exception:
            self._cfg = {}
        self._host = self._cfg.get("host", "127.0.0.1")
        self._hermes_port = int(self._cfg.get("port", 11434))
        self._model = agent_row.get("model") or self._cfg.get("model", "hermes3-llama3.1-8b")

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
            message=f"HermesAdapter.{method}() is not yet implemented. "
                    f"See runtime/backends/hermes.py to add it.",
            retryable=False,
        )

    def start(self) -> dict:
        return self._not_implemented("start")

    def stop(self) -> dict:
        return self._not_implemented("stop")

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
