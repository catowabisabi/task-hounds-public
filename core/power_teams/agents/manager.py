"""
manager.py — Manager agent cycle.

The Manager reads the human directive (or worker report), sends a structured
prompt to opencode, then parses the response to create suggestions, update
the handoff, and manage the plan/todo lists.
"""
from __future__ import annotations

import threading

from pathlib import Path

from power_teams.agents.base import (
    _acquire_manager_lock,
    _add_manager_message,
    _create_suggestion,
    _extract_section,
    _FORCE_PLANNING_INSTRUCTION,
    _FORCE_TODO_INSTRUCTION,
    _get_active_suggestion,
    _get_latest_handoff,
    _persist_plan_and_todos_from,
    _parse_todo_block,
    _parse_todo_update_json,
    _list_manager_messages,
    _release_manager_lock,
    _upsert_handoff,
    apply_handoff_update,
    connect,
    get_active_session_id,
    get_settings,
    handoff_summary,
    log,
    opencode_env,
    read_text,
    repair_mojibake,
    save_settings,
    send_to_agent,
    user_input_path,
    utc_now,
    worker_report_path,
    worker_status_path,
    write_text,
    DB_PATH,
    ROOT,
)
from power_teams.db import (
    get_active_reviewer_session,
    get_agent,
    get_latest_user_directive,
    get_latest_worker_report,
    get_reviewer_feedback,
    is_reviewer_timeout,
    mark_reviewer_timeout,
    update_user_directive_status,
    update_suggestion,
)

import json
import subprocess
import time
import uuid


# ── Manager format instructions ───────────────────────────────────────────────

_MANAGER_FORMAT_INSTRUCTIONS = (
    "Respond using ONLY the following XML sections. "
    "Do not include any text outside these tags.\n\n"
    "ROLE BOUNDARY:\n"
    "You are the Manager, not the Worker. Do not modify project files. "
    "Do not call edit, write, patch, shell, or file-changing tools. "
    "You may inspect project context only when needed, then create a precise Worker task in <SUGGESTION_CONTENT>. "
    "All implementation must be delegated to the Worker through the suggestion queue.\n\n"
    "<MANAGER_MESSAGE>\n"
    "Your message to the human. Be warm, conversational, and proactive:\n"
    "- Summarize what was accomplished in friendly language\n"
    "- Share your thinking process briefly (show personality)\n"
    "- Proactively ask if there's anything else they'd like to improve or add\n"
    "- Suggest creative ideas based on the project context\n"
    "- Use natural, engaging tone (not robotic)\n"
    "</MANAGER_MESSAGE>\n\n"
    "<SUGGESTION_CONTENT>\n"
    "The precise task instruction for the Worker. Include all necessary context.\n"
    "One atomic task only. Reference specific files and acceptance criteria.\n"
    "For continuous improvement, propose enhancements that add real value.\n"
    "</SUGGESTION_CONTENT>\n\n"
    "<SUGGESTION_VERIFICATION>\n"
    "A concise checklist the Worker can use to verify the task is done.\n"
    "Each line: [ ] <check>\n"
    "</SUGGESTION_VERIFICATION>\n\n"
    "<HANDOFF_UPDATE>\n"
    "A JSON object with only the changed fields. Valid keys:\n"
    "human_requirements, working_direction, file_structure, important_files,\n"
    "available_scripts, existing_solutions, references_demos,\n"
    "macro_flow, current_task, current_micro_flow,\n"
    "human_concerns, tested_files, known_bugs, completion_criteria.\n"
    "Arrays must be valid JSON arrays. Omit unchanged fields entirely.\n"
    "</HANDOFF_UPDATE>\n\n"
    "GUIDELINES FOR PROACTIVE ENGAGEMENT:\n"
    "1. After completing tasks, behave like an autonomous product owner.\n"
    "   Find the next highest-value improvement and create a worker task for it.\n"
    "2. Choose improvements based on:\n"
    "   - Industry best practices for similar projects\n"
    "   - Common user needs that aren't yet addressed\n"
    "   - Performance, UX, accessibility opportunities\n"
    "   - Testing, documentation, maintainability gaps\n"
    "3. Show initiative by creating next steps before being asked.\n"
    "4. Do not wait for user permission before creating the next useful worker task.\n"
    "   If there is a clear product, UX, quality, test, documentation, or reliability improvement, create it.\n"
    "5. Only use <DIRECTIVE_COMPLETE/> when the user explicitly says to stop\n"
    "   OR when all current requirements are met AND there is no meaningful improvement left to propose\n"
    "6. Balance autonomy with respect - explain what you are doing and why.\n"
    "\n"
    "STOP SIGNAL:\n"
    "If you are certain the project is complete and the automation loop should stop, include this exact line inside <MANAGER_MESSAGE>:\n"
    "TASK_HOUNDS_STOP_LOOP\n"
    "Only do this when there is no useful next worker task.\n"
)


def _build_manager_instructions() -> str:
    """Return format instructions with optional settings-driven prefixes."""
    settings = get_settings()
    prefix = ""
    if settings.get("force_planning"):
        prefix += _FORCE_PLANNING_INSTRUCTION
    if settings.get("force_todo"):
        prefix += _FORCE_TODO_INSTRUCTION
    return prefix + _MANAGER_FORMAT_INSTRUCTIONS


def _generate_session_name(directive: str) -> None:
    """Background: call LLM to produce a short session name, then persist via API."""
    settings = get_settings()
    session_id = settings.get("active_project_session")
    if not session_id:
        return
    try:
        agent_row = dict(get_agent("manager") or {})
        if not agent_row:
            return
        prompt = (
            "Give a 3-5 word title for this task. "
            "Reply with ONLY the title — no punctuation, no explanation.\n\n"
            f"Task: {directive[:400]}"
        )
        cmd = [
            "opencode", "run",
            "--format", "json",
            "--model", (agent_row.get("model") or "claude-haiku-4-5-20251001"),
            "--dangerously-skip-permissions",
        ]
        env = opencode_env()
        env["OPENCODE_BASE_URL"] = f"http://{agent_row['host']}:{agent_row['port']}"
        result = subprocess.run(
            cmd, input=prompt, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            env=env, timeout=60,
        )
        name = ""
        for line in result.stdout.splitlines():
            try:
                ev = json.loads(line)
                if ev.get("type") == "text":
                    txt = ((ev.get("part") or {}).get("text") or ev.get("text") or "").strip()
                    if txt:
                        name = txt
                        break
                elif ev.get("type") in ("assistant", "message"):
                    content = ev.get("content") or ""
                    if isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "text":
                                name = (b.get("text") or "").strip()
                                break
                    elif isinstance(content, str):
                        name = content.strip()
                    if name:
                        break
            except Exception:
                continue
        if not name:
            words = directive.split()
            name = " ".join(words[:6])
        name = name.strip().rstrip(".").strip()[:80]
        if not name:
            return
        with connect(DB_PATH) as db:
            db.execute(
                "UPDATE project_sessions SET name=?, name_generated=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (name, session_id)
            )
            db.commit()
        log(f"Session named: '{name}'")
    except Exception as exc:
        log(f"Session naming failed: {exc}")


def _current_plan_todo_context(session_id: str | None) -> str:
    if not session_id:
        return "(no active project session)"
    try:
        with connect(DB_PATH) as db:
            plan = db.execute(
                "SELECT content FROM session_plan WHERE session_id=?",
                (session_id,),
            ).fetchone()
            todos = db.execute(
                """SELECT id, content, status, owner, position FROM session_todos
                   WHERE session_id=?
                   ORDER BY parent_id IS NOT NULL, parent_id, position, id""",
                (session_id,),
            ).fetchall()
        lines = ["=== CURRENT MANAGER PLAN ===", plan["content"] if plan and plan["content"] else "(none)", "", "=== CURRENT TODO LIST ==="]
        if todos:
            for row in todos:
                lines.append(
                    f"- id={row['id']} status={row['status']} position={row['position']} "
                    f"owner={row['owner'] or 'unknown'} content={row['content']}"
                )
        else:
            lines.append("(none)")
        return "\n".join(lines)
    except Exception as exc:
        return f"(failed to load plan/todos: {exc})"


def _unprocessed_human_manager_messages(messages: list) -> tuple[list[str], int | None]:
    settings = get_settings()
    session_id = get_active_session_id() or "legacy"
    processed = settings.get("processed_manager_message_ids", {})
    last_seen = int(processed.get(session_id, 0) or 0)
    notes = []
    latest_id = None
    for msg in reversed(messages):
        content = msg["content"] if "content" in msg.keys() else ""
        msg_id = int(msg["id"] if "id" in msg.keys() else 0)
        if msg_id > last_seen and content.startswith("Human message to manager:"):
            notes.append(content)
            latest_id = max(latest_id or 0, msg_id)
    return notes, latest_id


def _mark_human_manager_messages_processed(latest_id: int | None) -> None:
    if not latest_id:
        return
    settings = get_settings()
    session_id = get_active_session_id() or "legacy"
    processed = dict(settings.get("processed_manager_message_ids", {}))
    processed[session_id] = max(int(processed.get(session_id, 0) or 0), int(latest_id))
    settings["processed_manager_message_ids"] = processed
    save_settings(settings)


# ── Manager cycle entry point ─────────────────────────────────────────────────

def manager_cycle() -> None:
    if not _acquire_manager_lock():
        log("manager_cycle: another manager is running, skipping")
        return
    try:
        _manager_cycle_impl()
    finally:
        _release_manager_lock()


def _manager_cycle_impl() -> None:
    ps_id = get_active_session_id()
    if ps_id:
        try:
            with connect(DB_PATH) as _c:
                row = _c.execute(
                    "SELECT workspace_path FROM project_sessions WHERE id=?", (ps_id,)
                ).fetchone()
            if row and row["workspace_path"]:
                if not Path(row["workspace_path"]).exists():
                    log(f"ERROR: workspace_path_missing for session {ps_id}: {row['workspace_path']}")
                    from power_teams.db import update_agent
                    update_agent("manager", state="error", last_error="workspace_path_missing")
                    return
        except Exception as exc:
            log(f"ERROR checking workspace_path for session {ps_id}: {exc}")
            return

    directive_row = None
    if ps_id:
        directive_row = get_latest_user_directive(ps_id, status="pending", path=DB_PATH)
    user_request = directive_row["directive"] if directive_row else read_text(user_input_path())
    try:
        worker_status = dict(get_agent("worker") or {}).get("state") or "idle"
    except Exception:
        worker_status = read_text(worker_status_path()).lower() or "idle"
    worker_report_row = get_latest_worker_report(ps_id, path=DB_PATH) if ps_id else None
    worker_report = worker_report_row["report"] if worker_report_row else read_text(worker_report_path())
    worker_has_report = bool(
        worker_report and worker_report not in ("# Worker Report\n", "")
    )

    active_suggestion = _get_active_suggestion()
    handoff = _get_latest_handoff()
    handoff_ctx = handoff_summary(handoff)
    recent_messages = _list_manager_messages()[:8]
    human_notes = []
    for msg in recent_messages:
        content = msg["content"] if "content" in msg.keys() else ""
        if content.startswith("Human message to manager:"):
            human_notes.append(content)
    human_notes_ctx = "\n".join(f"- {note}" for note in human_notes) or "(none)"
    unprocessed_notes, latest_human_note_id = _unprocessed_human_manager_messages(recent_messages)
    plan_todo_ctx = _current_plan_todo_context(ps_id)

    # --- Scenario 1: New human directive ---
    if user_request:
        log("Manager: processing new user directive")
        try:
            ps_id = get_active_session_id()
            if ps_id:
                with connect(DB_PATH) as _c:
                    row = _c.execute(
                        "SELECT name FROM project_sessions WHERE id=?", (ps_id,)
                    ).fetchone()
                if row and row["name"] is None:
                    threading.Thread(
                        target=_generate_session_name,
                        args=(user_request,),
                        daemon=True,
                    ).start()
        except Exception:
            pass
        prompt = (
            "You are the Manager agent — enthusiastic, proactive, and ready to help!\n\n"
            "=== PROJECT CONTEXT ===\n"
            f"{handoff_ctx}\n\n"
            "=== RECENT HUMAN MESSAGES TO MANAGER ===\n"
            f"{human_notes_ctx}\n\n"
            f"{plan_todo_ctx}\n\n"
            "=== NEW HUMAN DIRECTIVE ===\n"
            f"{user_request}\n\n"
            "Your job:\n"
            "1. UNDERSTAND INTENT: Read between the lines. What is the user REALLY trying to achieve?\n"
            "2. SHOW ENTHUSIASM: Start your message with positive energy:\n"
            "   - 'Great idea!' / 'I love this direction!' / 'Let's make this happen!'\n"
            "3. PLAN STRATEGICALLY: Think about the full scope, not just the immediate request.\n"
            "   - What related features might be useful?\n"
            "   - What could we build on top of this?\n"
            "   - How does this fit into the bigger picture?\n"
            "4. BREAK INTO TASKS: Create the smallest first step for the Worker.\n"
            "   - One task at a time. We'll iterate based on results.\n"
            "   - Include exact file paths, function names, and clear acceptance criteria.\n"
            "   - Reference existing solutions so the Worker does NOT reinvent them.\n"
            "5. COMMUNICATE YOUR PLAN:\n"
            "   - Explain what you're going to do first\n"
            "   - Mention potential next steps (so they know you're thinking ahead)\n"
            "   - Tell the human which first worker task you are queuing now\n"
            "6. BE PROACTIVE ABOUT FOLLOW-UP:\n"
            "   - Keep looking for the next useful product/UX/quality/test/docs improvement\n"
            "   - Do not block the automation loop waiting for permission when the next step is clear\n\n"
            + _build_manager_instructions()
        )
        response = send_to_agent("manager", prompt)
        _handle_manager_response(response, fallback_task=user_request)
        if directive_row:
            update_user_directive_status(int(directive_row["id"]), "processed", path=DB_PATH)
        write_text(user_input_path(), "")
        return

    if unprocessed_notes:
        log(f"Manager: processing {len(unprocessed_notes)} human manager message(s)")
        active_worker_task = active_suggestion if (active_suggestion and active_suggestion["status"] in ("pending", "paused", "released")) else None
        current_worker_task = (
            f"Suggestion #{active_worker_task['id']} status={active_worker_task['status']}\n"
            f"{active_worker_task['content']}\n\n"
            f"Verification:\n{active_worker_task['verification'] or '(none)'}"
        ) if active_worker_task else "(no active worker task to revise)"
        prompt = (
            "You are the Manager agent. The human sent guidance directly to you.\n\n"
            "=== PROJECT CONTEXT ===\n"
            f"{handoff_ctx}\n\n"
            f"{plan_todo_ctx}\n\n"
            "=== CURRENT TO-WORKER MESSAGE / ACTIVE SUGGESTION ===\n"
            f"{current_worker_task}\n\n"
            "=== NEW HUMAN MESSAGES TO MANAGER ===\n"
            + "\n".join(f"- {note}" for note in unprocessed_notes)
            + "\n\n"
            "Your job:\n"
            "1. Reply to the human in <MANAGER_MESSAGE>, acknowledging what changed.\n"
            "2. Revise <PLAN> and <TODO_LIST> to reflect the human guidance.\n"
            "3. Rewrite the to-worker instruction in <SUGGESTION_CONTENT> if a worker should act.\n"
            "4. If there is an active pending/released worker task, your <SUGGESTION_CONTENT> will replace it.\n"
            "5. If no worker action is needed, explain that clearly and use TASK_HOUNDS_STOP_LOOP if the loop should stop.\n\n"
            + _build_manager_instructions()
        )
        response = send_to_agent("manager", prompt)
        replace_id = active_worker_task["id"] if active_worker_task else None
        _handle_manager_response(
            response,
            fallback_task="\n".join(unprocessed_notes),
            replace_suggestion_id=replace_id,
        )
        _mark_human_manager_messages_processed(latest_human_note_id)
        return

    # --- Scenario 2: Worker finished a released suggestion ---
    released = (
        active_suggestion
        if (active_suggestion and active_suggestion["status"] in ("released", "worker_done"))
        else None
    )

    if released and released["status"] == "worker_done" and worker_status == "idle" and worker_has_report:
        log(f"Manager: QA on suggestion #{released['id']}")

        reviewer_session = get_active_reviewer_session(released['id'])
        reviewer_feedback = None

        if reviewer_session:
            session_id = reviewer_session["id"]
            status = reviewer_session["status"]

            if status == "completed":
                reviewer_feedback = get_reviewer_feedback(released['id'])
                if reviewer_feedback:
                    log(f"✅ Reviewer completed. Including feedback in QA.")
                    log(f"   Notes: {reviewer_feedback['review_notes'][:100]}...")

            elif status == "running":
                log(f"Reviewer still running. Waiting up to 5 minutes...")
                wait_start = time.monotonic()
                got_feedback = False

                while time.monotonic() - wait_start < 300:
                    time.sleep(10)
                    with connect(DB_PATH) as _db:
                        _row = _db.execute(
                            "SELECT status FROM reviewer_sessions WHERE id=?",
                            (session_id,)
                        ).fetchone()
                    current_status = _row["status"] if _row else "unknown"

                    if current_status == "completed":
                        reviewer_feedback = get_reviewer_feedback(released['id'])
                        log(f"Reviewer completed after waiting. Including feedback.")
                        got_feedback = True
                        break

                    if current_status in ("failed", "timeout") or is_reviewer_timeout(session_id):
                        log(f"Reviewer timed out or failed ({current_status}). Proceeding without feedback.")
                        mark_reviewer_timeout(session_id)
                        break

                if not got_feedback and reviewer_feedback is None:
                    log(f"Reviewer did not complete within timeout. Proceeding without feedback.")

            else:
                log(f"⚠️ Reviewer status: {status}. Proceeding without feedback.")
        else:
            log(f"ℹ️ No reviewer session found. Proceeding with QA.")

        verification = released["verification"] or "(none provided)"
        suggestion_content = released["content"]

        qa_context = f"{handoff_ctx}\n\n"
        if reviewer_feedback:
            # sqlite3.Row has no .get() method — convert to dict for consistent access
            reviewer_feedback = dict(reviewer_feedback)
            qa_context += (
                "=== REVIEWER FEEDBACK (UI/UX Analysis) ===\n"
                f"**Observations:**\n{reviewer_feedback['review_notes']}\n\n"
                f"**Usability Issues:**\n{reviewer_feedback.get('usability_issues', 'None')}\n\n"
                f"**Style Feedback:**\n{reviewer_feedback.get('style_feedback', 'N/A')}\n\n"
                f"**Documented Scripts:**\n{reviewer_feedback.get('scripts_documented', 'N/A')}\n\n"
            )

        prompt = (
            "You are the Manager agent — a proactive, creative partner who cares about quality.\n\n"
            "=== PROJECT CONTEXT ===\n"
            f"{qa_context}"
            "=== RECENT HUMAN MESSAGES TO MANAGER ===\n"
            f"{human_notes_ctx}\n\n"
            f"{plan_todo_ctx}\n\n"
            "=== TASK THAT WAS ASSIGNED TO WORKER ===\n"
            f"{suggestion_content}\n\n"
            "=== ACCEPTANCE CRITERIA ===\n"
            f"{verification}\n\n"
            "=== WORKER REPORT ===\n"
            f"{worker_report}\n\n"
            "Your job:\n"
            "1. QUALITY CHECK: Verify each criterion is met. Be thorough but fair.\n"
            "2. DECISION: Clearly state PASS or FAIL in your MANAGER_MESSAGE.\n"
            "3. UPDATE TODO LIST (CRITICAL):\n"
            "   - Mark every completed item from the current task as [x] in <TODO_LIST>.\n"
            "   - Also mark every completed item as status=\"completed\" in <TODO_UPDATE_JSON>.\n"
            "   - Use the existing todo id values from CURRENT TODO LIST in <TODO_UPDATE_JSON>.\n"
            "   - Remove obsolete completed detail items if they no longer help the dashboard.\n"
            "   - If you create a new worker task, include its concrete subtasks as new [ ] TODO_LIST items.\n"
            "   - Never leave completed work as unchecked [ ] items.\n"
            "4. UPDATE HANDOFF: Mark progress, add tested files, note any bugs found.\n"
            "5. PROACTIVE PRODUCT OWNER MODE (CRITICAL):\n"
            "   After QA passes, think like a creative product manager:\n"
            "   - What would make this BETTER for users? (UX, features, polish)\n"
            "   - What best practices are missing? (testing, error handling, docs)\n"
            "   - What edge cases might break? (robustness, validation)\n"
            "   - What could be faster/smoother? (performance optimization)\n"
            "   - Research mentally: How do top apps/sites handle similar features?\n"
            "   \n"
            "   Then create exactly one highest-value next worker task in <SUGGESTION_CONTENT>.\n"
            "   Do not merely ask the user whether to proceed when the next step is obvious.\n"
            "6. HUMANIZE YOUR COMMUNICATION:\n"
            "   - Start with enthusiasm: 'Great news!' / 'Nice work on this!'\n"
            "   - Explain your reasoning: 'I'm thinking we could... because...'\n"
            "   - Tell the user what you are doing next, unless stopping.\n"
            "   - Offer optional alternatives only in addition to a concrete next worker task.\n"
            "7. ONLY use <DIRECTIVE_COMPLETE/> or TASK_HOUNDS_STOP_LOOP if:\n"
            "   - All requirements are fully met AND\n"
            "   - Completed work has been marked [x] or removed from <TODO_LIST> AND\n"
            "   - There is no useful next product/UX/quality/test/docs/reliability task.\n\n"
            + _build_manager_instructions()
        )
        response = send_to_agent("manager", prompt)

        msg_upper = _extract_section(response, "MANAGER_MESSAGE").upper()
        qa_passed = "PASS" in msg_upper or "APPROVED" in msg_upper

        update_suggestion(released["id"], status="done")
        log(f"Suggestion #{released['id']} marked done. QA={'PASS' if qa_passed else 'FAIL'}")

        _handle_manager_response(response)

        write_text(worker_report_path(), "# Worker Report\n")
        write_text(worker_status_path(), "idle\n")
        return

    # --- Scenario 3: Proactive planning ---
    pending = (
        active_suggestion
        if (active_suggestion and active_suggestion["status"] in ("pending", "paused"))
        else None
    )

    if pending:
        log(f"Manager: analysing pending human suggestion #{pending['id']}")
        prompt = (
            "You are the Manager agent. A human added a suggestion to the queue.\n\n"
            "=== PROJECT CONTEXT ===\n"
            f"{handoff_ctx}\n\n"
            "=== RECENT HUMAN MESSAGES TO MANAGER ===\n"
            f"{human_notes_ctx}\n\n"
            f"{plan_todo_ctx}\n\n"
            "=== HUMAN SUGGESTION QUEUE ITEM ===\n"
            f"{pending['content']}\n\n"
            "Your job:\n"
            "1. Analyse the request and convert it into an actionable project plan.\n"
            "2. Write the detailed planning into <PLAN>.\n"
            "3. Convert every concrete planning step into <TODO_LIST> items.\n"
            "4. Create one precise first worker task in <SUGGESTION_CONTENT>.\n"
            "5. Include acceptance checks in <SUGGESTION_VERIFICATION>.\n"
            "6. Explain to the human how you interpreted the suggestion in <MANAGER_MESSAGE>.\n\n"
            + _build_manager_instructions()
        )
        response = send_to_agent("manager", prompt)
        update_suggestion(pending["id"], status="done")
        _handle_manager_response(response, fallback_task=pending["content"])
        return

    if worker_status != "idle":
        log("Manager: worker is busy, skipping proactive planning")
        return

    log("Manager: proactive planning")
    prompt = (
        "You are the Manager agent — a proactive creative partner.\n\n"
        "=== PROJECT CONTEXT ===\n"
        f"{handoff_ctx}\n\n"
        "=== RECENT HUMAN MESSAGES TO MANAGER ===\n"
        f"{human_notes_ctx}\n\n"
        f"{plan_todo_ctx}\n\n"
        "SITUATION: No active task is running. This is your chance to show initiative!\n\n"
        "Your job:\n"
        "1. CREATIVE EXPLORATION: Think beyond just 'next step'. Consider:\n"
        "   - What features would delight users? (surprise & delight)\n"
        "   - What polish makes this feel professional? (animations, transitions, feedback)\n"
        "   - What accessibility improvements help more users? (keyboard nav, ARIA, contrast)\n"
        "   - What performance optimizations matter? (load time, smoothness, memory)\n"
        "   - What testing would give confidence? (unit tests, integration tests)\n"
        "   - What documentation helps future developers? (README, comments, examples)\n"
        "   \n"
        "2. RESEARCH MENTALLY: Draw on your knowledge of:\n"
        "   - Industry best practices for similar projects\n"
        "   - Common patterns in successful apps/websites\n"
        "   - User experience research findings\n"
        "   - Technical debt warning signs\n"
        "   \n"
        "3. PROPOSE WITH ENTHUSIASM:\n"
        "   - 'I've been thinking... we could add [feature] because [benefit]'\n"
        "   - 'I noticed [observation]. Want me to improve that?'\n"
        "   - 'Here's an idea: [creative suggestion]. Thoughts?'\n"
        "   \n"
        "4. CREATE THE TASK: Once you identify an improvement:\n"
        "   - Make it specific and actionable for the Worker\n"
        "   - Include exact file paths and acceptance criteria\n"
        "   - Reference existing code to build upon\n"
        "   \n"
        "5. ENGAGE THE HUMAN:\n"
        "   - Explain WHY this improvement matters\n"
        "   - Tell them what concrete worker task you are creating next\n"
        "   - Offer alternatives if relevant, but do not block the loop waiting for permission\n"
        "   \n"
        "6. ONLY stop if there is no useful product/UX/quality/test/docs/reliability task left.\n\n"
        + _build_manager_instructions()
    )
    response = send_to_agent("manager", prompt)
    _handle_manager_response(
        response,
        fallback_task=(
            "Continue executing the current manager plan. Pick the highest-priority pending todo, "
            "turn it into a concrete implementation task, and complete one useful step."
        ),
    )


def _handle_manager_response(
    response: str,
    fallback_task: str | None = None,
    replace_suggestion_id: int | None = None,
) -> None:
    """
    Parse a structured manager response and persist all parts:
    - PLAN             -> session_plan
    - TODO_LIST        -> session_todos
    - MANAGER_MESSAGE  -> manager_messages
    - SUGGESTION_CONTENT + SUGGESTION_VERIFICATION -> suggestion_queue
    - HANDOFF_UPDATE   -> project_handoff

    Retries up to 3 times if PLAN, TODO_LIST, or TODO_UPDATE_JSON is missing.
    """
    MAX_RETRIES = 3
    _retry = 0

    while True:
        response = repair_mojibake(response or "")
        has_plan = bool(_extract_section(response, "PLAN"))
        has_todo = bool(_extract_section(response, "TODO_LIST"))
        todo_json_items = _parse_todo_update_json(_extract_section(response, "TODO_UPDATE_JSON"))
        has_todo_json = bool(todo_json_items)

        _persist_plan_and_todos_from(response, owner="manager")

        if (not has_plan or not has_todo or not has_todo_json) and _retry < MAX_RETRIES:
            missing = []
            if not has_plan: missing.append("<PLAN>")
            if not has_todo: missing.append("<TODO_LIST>")
            if not has_todo_json: missing.append("<TODO_UPDATE_JSON>")
            log(f"⚠ Manager response missing {', '.join(missing)} — asking manager to retry (attempt {_retry + 1}/{MAX_RETRIES})")
            correction = (
                f"Your previous response was missing the required {' and '.join(missing)} block(s).\n"
                "Re-emit your COMPLETE response now, including:\n"
                "  - A full <PLAN>...</PLAN> block (Goal, Steps, Success Criteria)\n"
                "  - A full <TODO_LIST>...</TODO_LIST> block (current top-level items with status)\n"
                "  - A full <TODO_UPDATE_JSON>...</TODO_UPDATE_JSON> block with valid JSON; use existing todo IDs from CURRENT TODO LIST; mark completed work as status=\"completed\" here.\n"
                "  - The MANAGER_MESSAGE, SUGGESTION_CONTENT, SUGGESTION_VERIFICATION, and HANDOFF_UPDATE you intended.\n\n"
                "Do not claim completion in MANAGER_MESSAGE unless TODO_UPDATE_JSON sets the matching todo status to completed.\n"
                "Current todo context with IDs:\n"
                f"{_current_plan_todo_context(get_active_session_id())}\n\n"
                "Do not abbreviate. The UI parses these blocks directly; missing blocks mean the cycle is incomplete.\n\n"
                + _build_manager_instructions()
            )
            response = send_to_agent("manager", correction)
            _retry += 1
            continue
        break

    if not has_plan:
        log(f"⚠ Manager STILL missing <PLAN> after {_retry} retries — accepting incomplete cycle")
    if not has_todo:
        log(f"⚠ Manager STILL missing <TODO_LIST> after {_retry} retries — accepting incomplete cycle")

    if not has_todo_json:
        msg = (
            "Manager response rejected: missing or invalid <TODO_UPDATE_JSON> after "
            f"{_retry} retries. I did not create a worker task from this response because "
            "todo status must be updated through the database JSON block."
        )
        log(msg)
        _add_manager_message(msg)
        return

    manager_msg = _extract_section(response, "MANAGER_MESSAGE")
    suggestion_content = _extract_section(response, "SUGGESTION_CONTENT")
    suggestion_verification = _extract_section(response, "SUGGESTION_VERIFICATION")
    todo_items = _parse_todo_block(_extract_section(response, "TODO_LIST"))

    if not manager_msg and response.strip():
        manager_msg = "Manager returned an unstructured response. Raw response was saved for debugging."

    if not suggestion_content and not fallback_task and todo_items:
        first_pending = next((item for item in todo_items if item.get("status") != "completed"), None)
        if first_pending:
            fallback_task = (
                "Execute this manager todo as the next worker task. "
                "Keep the work scoped and report files changed.\n\n"
                f"{first_pending['content']}"
            )

    if not suggestion_content and fallback_task:
        suggestion_content = (
            "Execute this human directive exactly. Keep the work scoped and report files changed.\n\n"
            f"{fallback_task}"
        )
        suggestion_verification = (
            "[ ] Human requested files/folders are created at the specified paths\n"
            "[ ] Implementation satisfies the listed requirements\n"
            "[ ] Worker report includes files changed and how to open/run the result"
        )
        log("Manager response had no SUGGESTION_CONTENT; created fallback worker task from user directive")

    fallback_handoff = None
    if fallback_task:
        fallback_handoff = {
            "human_requirements": [fallback_task],
            "working_direction": "Execute the human directive through the manager/worker file bridge.",
            "current_task": fallback_task[:1000],
            "current_micro_flow": ["Create or update the worker suggestion", "Release the task to worker", "Verify worker report"],
            "completion_criteria": [
                "A worker task exists for the human directive",
                "Worker completes the requested files or changes",
                "Worker report explains what changed and how to verify it",
            ],
        }

    def _is_no_further_task(content: str) -> bool:
        text = (content or "").strip().lower()
        return (
            text.startswith("no further")
            or "no further task" in text
            or "no further worker task" in text
            or "\u7121\u65b0\u4efb\u52d9" in text
        )

    directive_complete = "<DIRECTIVE_COMPLETE" in response or "TASK_HOUNDS_STOP_LOOP" in manager_msg
    if suggestion_content and _is_no_further_task(suggestion_content):
        directive_complete = True

    if manager_msg:
        _add_manager_message(manager_msg)
        log(f"Manager message saved ({len(manager_msg)} chars)")

    if directive_complete:
        log("Manager signalled DIRECTIVE_COMPLETE — no new suggestion created")
        suggestion_content = None

    def _ensure_todo_for_suggestion(content: str) -> None:
        session_id = get_active_session_id()
        if not session_id or not content.strip():
            return
        title = content.strip().splitlines()[0][:180]
        if _is_no_further_task(title):
            return
        with connect(DB_PATH) as conn:
            existing = conn.execute(
                "SELECT id FROM session_todos WHERE session_id=? AND content=? LIMIT 1",
                (session_id, title),
            ).fetchone()
            if existing:
                return
            pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM session_todos WHERE session_id=? AND parent_id IS NULL",
                (session_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO session_todos
                     (id, session_id, parent_id, content, status, priority, position, owner)
                   VALUES (?, ?, NULL, ?, 'pending', 'medium', ?, 'manager')""",
                (str(uuid.uuid4()), session_id, title, int(pos) + 1),
            )
            conn.commit()

    if suggestion_content and not directive_complete:
        handoff = _get_latest_handoff()
        handoff_ver = handoff["version"] if handoff else None
        if replace_suggestion_id:
            update_suggestion(
                replace_suggestion_id,
                content=suggestion_content,
                verification=suggestion_verification or None,
                status="released",
            )
            log(f"Suggestion #{replace_suggestion_id} revised from human manager message")
            _ensure_todo_for_suggestion(suggestion_content)
        else:
            sid = _create_suggestion(
                content=suggestion_content,
                verification=suggestion_verification or None,
                handoff_version=handoff_ver,
            )
            log(f"New suggestion #{sid} created (status=released)")
            _ensure_todo_for_suggestion(suggestion_content)

    updated = apply_handoff_update(response, updated_by="manager")
    if fallback_handoff and updated is None:
        new_ver = _upsert_handoff(updated_by="manager-fallback", **fallback_handoff)
        log(f"Fallback handoff updated to version {new_ver}")
