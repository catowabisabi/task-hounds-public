"""
worker.py — Worker agent cycle.

The Worker reads the active suggestion from SQLite, executes the task via
opencode, writes a report, then triggers the reviewer in a background thread.
"""
from __future__ import annotations

from power_teams.agents.base import (
    _get_active_suggestion,
    _get_latest_handoff,
    get_active_session_id,
    handoff_summary,
    log,
    read_text,
    send_to_agent,
    update_agent,
    utc_now,
    worker_report_path,
    worker_status_path,
    write_text,
)
from power_teams.db import add_worker_report, update_suggestion


def worker_cycle() -> None:
    """
    Worker reads the single released suggestion + compact handoff,
    executes the task, writes a report.
    """
    suggestion = _get_active_suggestion()

    if suggestion is None or suggestion["status"] != "released":
        update_agent("worker", state="idle", last_seen=utc_now())
        write_text(worker_status_path(), "idle\n")
        return

    handoff = _get_latest_handoff()
    handoff_ctx = handoff_summary(handoff)
    verification = suggestion["verification"] or ""
    human_comment = suggestion["human_comment"] or ""

    log(f"Worker: starting on suggestion #{suggestion['id']}")
    write_text(worker_status_path(), "busy\n")
    update_agent("worker", state="busy", last_seen=utc_now())

    prompt = (
        "You are the Worker agent. Execute the assigned task precisely.\n\n"
        "=== PROJECT CONTEXT (read-only) ===\n"
        f"{handoff_ctx}\n\n"
        "=== YOUR TASK ===\n"
        f"{suggestion['content']}\n\n"
    )

    if verification:
        prompt += (
            "=== ACCEPTANCE CRITERIA ===\n"
            f"{verification}\n\n"
        )

    if human_comment:
        prompt += (
            "=== HUMAN COMMENT ===\n"
            f"{human_comment}\n\n"
        )

    prompt += (
        "Instructions:\n"
        "- Work step by step. Use bash and file tools as needed.\n"
        "- Do NOT reinvent solutions that already exist in the project context above.\n"
        "- When done, write a detailed completion report including:\n"
        "  * What you implemented / changed\n"
        "  * Files created or modified (with paths)\n"
        "  * How each acceptance criterion was satisfied\n"
        "  * Any issues or edge cases noticed\n"
    )

    report = send_to_agent("worker", prompt)
    session_id = get_active_session_id()
    if session_id:
        add_worker_report(session_id, report)
    write_text(worker_report_path(), f"# Worker Report\n\n{report}\n")

    update_suggestion(suggestion["id"], status="worker_done")

    # Trigger reviewer in background (non-blocking)
    try:
        from power_teams.agents.reviewer import _trigger_reviewer_async
        _trigger_reviewer_async(suggestion["id"])
        log(f"✅ Reviewer triggered for suggestion #{suggestion['id']}")
    except Exception as exc:
        log(f"⚠️ Failed to trigger reviewer: {exc}")

    write_text(worker_status_path(), "idle\n")
    update_agent("worker", state="idle", last_seen=utc_now())
    log(f"Worker: finished suggestion #{suggestion['id']}, report written")
