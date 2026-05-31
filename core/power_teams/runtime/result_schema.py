"""
result_schema.py — Unified result contract for all backend adapters.

Every adapter method (run, health, start, stop, logs) returns a JsonResult dict.
UI and runner code only need to check result["ok"] — they never inspect
backend-specific fields.

Success:
    {
        "ok": True,
        "backend": "opencode",
        "agent": "manager",
        "run_id": "run_abc123",
        "status": "completed",
        "output": {
            "text": "...",
            "files": [],
            "metrics": {}
        },
        "error": None
    }

Failure:
    {
        "ok": False,
        "backend": "opencode",
        "agent": "manager",
        "run_id": "run_abc123",
        "status": "failed",
        "output": None,
        "error": {
            "type": "ConnectionError",
            "message": "Backend process not reachable",
            "retryable": True,
            "raw": "WinError 10061..."
        }
    }
"""
from __future__ import annotations

import uuid
from typing import Any


# ── Public status values ────────────────────────────────────────────────────
STATUS_COMPLETED = "completed"
STATUS_FAILED    = "failed"
STATUS_RUNNING   = "running"
STATUS_HEALTHY   = "healthy"
STATUS_UNHEALTHY = "unhealthy"
STATUS_STARTED   = "started"
STATUS_STOPPED   = "stopped"


def new_run_id() -> str:
    """Generate a short unique run identifier."""
    return "run_" + uuid.uuid4().hex[:8]


# ── Result constructors ─────────────────────────────────────────────────────

def ok(
    *,
    backend: str,
    agent: str,
    status: str = STATUS_COMPLETED,
    run_id: str | None = None,
    text: str = "",
    files: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    **extra: Any,
) -> dict:
    """Build a successful JsonResult."""
    return {
        "ok": True,
        "backend": backend,
        "agent": agent,
        "run_id": run_id or new_run_id(),
        "status": status,
        "output": {
            "text": text,
            "files": files or [],
            "metrics": metrics or {},
            **extra,
        },
        "error": None,
    }


def err(
    *,
    backend: str,
    agent: str,
    message: str,
    error_type: str = "Error",
    retryable: bool = False,
    raw: str = "",
    run_id: str | None = None,
    status: str = STATUS_FAILED,
) -> dict:
    """Build a failed JsonResult."""
    return {
        "ok": False,
        "backend": backend,
        "agent": agent,
        "run_id": run_id or new_run_id(),
        "status": status,
        "output": None,
        "error": {
            "type": error_type,
            "message": message,
            "retryable": retryable,
            "raw": raw,
        },
    }


def is_retryable(result: dict) -> bool:
    """Return True if the error is marked as retryable."""
    if result.get("ok"):
        return False
    error = result.get("error") or {}
    return bool(error.get("retryable"))


def get_text(result: dict) -> str:
    """Extract output text from a successful result, or '' on failure."""
    if not result.get("ok"):
        return ""
    output = result.get("output") or {}
    return output.get("text", "")


def get_error_message(result: dict) -> str:
    """Extract error message, or '' on success."""
    if result.get("ok"):
        return ""
    error = result.get("error") or {}
    return error.get("message", "unknown error")
