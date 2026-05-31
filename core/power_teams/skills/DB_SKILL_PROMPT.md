# Task Hounds DB Skill — Agent Prompt Snippet

You MUST NOT directly read or write the Task Hounds SQLite database.

## DB Skill

All database access MUST go through the Task Hounds DB Skill.

### Identity Required on Every Call

| Field | Value | Example |
|-------|-------|---------|
| `project_session_id` | Current project session ID | `ps_abc123` |
| `role` | Your agent role | `manager`, `worker`, `reviewer`, `chat` |
| `role_session_id` | `{project_session_id}:{role}` | `ps_abc123:manager` |

### Available Commands

```bash
# Read project context (handoff, active suggestion, messages)
python -m power_teams.skills.db_tool read-project-context \
  --project-session-id <id> --role <role> --role-session-id <id:role>

# Read a table (only: project_handoff, suggestion_queue, manager_messages,
#                session_plan, session_todos, reviewer_sessions, project_sessions)
python -m power_teams.skills.db_tool read-table \
  --project-session-id <id> --role <role> --role-session-id <id:role> \
  --table <table_name> --limit 50

# Execute a write operation
python -m power_teams.skills.db_tool write \
  --project-session-id <id> --role <role> --role-session-id <id:role> \
  --operation <operation_name> --payload-json '{...}'
```

### Role-Permitted Write Operations

**manager:** `append_manager_message`, `create_suggestion`, `update_suggestion_status`, `update_handoff`, `update_plan`, `update_todos`

**worker:** `append_worker_report`, `update_suggestion_status`, `update_worker_todos`

**reviewer:** `record_reviewer_feedback`, `create_followup_suggestion`, `update_reviewer_session`

**chat:** `append_chat_message`, `create_user_directive`, `update_chat_todos`

### Error Handling

If the skill returns `ok=false`, STOP the current write flow and report the error.

```json
{"ok": false, "error": {"type": "PermissionError", "message": "..."}}
```