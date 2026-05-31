"""
opencode_connect.py — HTTP client for OpenCode server REST API.

All endpoints from the OpenCode OpenAPI 3.1 spec.
No auth by default. Instantiate with host + port:

    oc = OpenCodeConnect("127.0.0.1", 4096)
    oc.health()                      # → {healthy, version}
    agents = oc.list_agents()         # → Agent[]
    sessions = oc.list_sessions()    # → Session[]
    msg = oc.send_message(sid, "hello")
"""

from __future__ import annotations

import json as _json
import urllib.error as _urlerr
import urllib.request as _urlreq
from typing import Any


class OpenCodeConnect:
    """HTTP client for the OpenCode server REST API."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4096, *, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.base = f"http://{host}:{port}"
        self.timeout = timeout

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get(self, path: str) -> Any:
        url = f"{self.base}{path}"
        req = _urlreq.Request(url, headers={"Accept": "application/json"})
        with _urlreq.urlopen(req, timeout=self.timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    def _post(self, path: str, body: dict | None = None) -> Any:
        url = f"{self.base}{path}"
        data = _json.dumps(body or {}).encode("utf-8") if body else b"{}"
        req = _urlreq.Request(url, data=data, headers={"Accept": "application/json", "Content-Type": "application/json"})
        with _urlreq.urlopen(req, timeout=self.timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    def _patch(self, path: str, body: dict) -> Any:
        url = f"{self.base}{path}"
        data = _json.dumps(body).encode("utf-8")
        req = _urlreq.Request(url, data=data, headers={"Accept": "application/json", "Content-Type": "application/json"})
        with _urlreq.urlopen(req, timeout=self.timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    def _delete(self, path: str) -> Any:
        url = f"{self.base}{path}"
        req = _urlreq.Request(url, method="DELETE", headers={"Accept": "application/json"})
        with _urlreq.urlopen(req, timeout=self.timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    # ── Global ───────────────────────────────────────────────────────────────

    def health(self) -> dict:
        """GET /global/health — server health and version."""
        return self._get("/global/health")

    # ── Project ──────────────────────────────────────────────────────────────

    def list_projects(self) -> list[dict]:
        """GET /project — list all projects."""
        return self._get("/project")

    def current_project(self) -> dict:
        """GET /project/current — get current project."""
        return self._get("/project/current")

    # ── Path / VCS ──────────────────────────────────────────────────────────

    def current_path(self) -> dict:
        """GET /path — get current path."""
        return self._get("/path")

    def vcs_info(self) -> dict:
        """GET /vcs — get VCS info for current project."""
        return self._get("/vcs")

    # ── Instance ─────────────────────────────────────────────────────────────

    def dispose_instance(self) -> bool:
        """POST /instance/dispose — destroy current instance."""
        return self._post("/instance/dispose")

    # ── Config ───────────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        """GET /config — get configuration."""
        return self._get("/config")

    def update_config(self, updates: dict) -> dict:
        """PATCH /config — update configuration."""
        return self._patch("/config", updates)

    def list_config_providers(self) -> dict:
        """GET /config/providers — list providers and default models."""
        return self._get("/config/providers")

    # ── Providers ────────────────────────────────────────────────────────────

    def list_providers(self) -> dict:
        """GET /provider — list all providers."""
        return self._get("/provider")

    def provider_auth(self) -> dict:
        """GET /provider/auth — get provider auth methods."""
        return self._get("/provider/auth")

    def oauth_authorize(self, provider_id: str) -> dict:
        """POST /provider/{id}/oauth/authorize — authorize via OAuth."""
        return self._post(f"/provider/{provider_id}/oauth/authorize", {})

    def oauth_callback(self, provider_id: str) -> bool:
        """POST /provider/{id}/oauth/callback — handle OAuth callback."""
        return self._post(f"/provider/{provider_id}/oauth/callback", {})

    # ── Sessions ─────────────────────────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """GET /session — list all sessions."""
        return self._get("/session")

    def create_session(self, *, parent_id: str | None = None, title: str | None = None) -> dict:
        """POST /session — create new session."""
        body = {}
        if parent_id is not None:
            body["parentID"] = parent_id
        if title is not None:
            body["title"] = title
        return self._post("/session", body)

    def all_session_statuses(self) -> dict:
        """GET /session/status — get status of all sessions."""
        return self._get("/session/status")

    def get_session(self, session_id: str) -> dict:
        """GET /session/:id — get session details."""
        return self._get(f"/session/{session_id}")

    def delete_session(self, session_id: str) -> bool:
        """DELETE /session/:id — delete session and all its data."""
        return self._delete(f"/session/{session_id}")

    def update_session(self, session_id: str, *, title: str | None = None) -> dict:
        """PATCH /session/:id — update session attributes."""
        body = {}
        if title is not None:
            body["title"] = title
        return self._patch(f"/session/{session_id}", body)

    def session_children(self, session_id: str) -> list[dict]:
        """GET /session/:id/children — get child sessions."""
        return self._get(f"/session/{session_id}/children")

    def session_todos(self, session_id: str) -> list[dict]:
        """GET /session/:id/todo — get todo list for session."""
        return self._get(f"/session/{session_id}/todo")

    def init_session(self, session_id: str, *, message_id: str, provider_id: str, model_id: str) -> bool:
        """POST /session/:id/init — analyze app and create AGENTS.md."""
        return self._post(
            f"/session/{session_id}/init",
            {"messageID": message_id, "providerID": provider_id, "modelID": model_id},
        )

    def fork_session(self, session_id: str, *, message_id: str | None = None) -> dict:
        """POST /session/:id/fork — fork at a message."""
        body = {}
        if message_id is not None:
            body["messageID"] = message_id
        return self._post(f"/session/{session_id}/fork", body)

    def abort_session(self, session_id: str) -> bool:
        """POST /session/:id/abort — abort running session."""
        return self._post(f"/session/{session_id}/abort", {})

    def share_session(self, session_id: str) -> dict:
        """POST /session/:id/share — share session."""
        return self._post(f"/session/{session_id}/share", {})

    def unshare_session(self, session_id: str) -> bool:
        """DELETE /session/:id/share — unshare session."""
        return self._delete(f"/session/{session_id}/share")

    def session_diff(self, session_id: str, *, message_id: str | None = None) -> list[dict]:
        """GET /session/:id/diff — get diff for session."""
        path = f"/session/{session_id}/diff"
        if message_id is not None:
            path += f"?messageID={message_id}"
        return self._get(path)

    def summarize_session(self, session_id: str, *, provider_id: str, model_id: str) -> bool:
        """POST /session/:id/summarize — summarize session."""
        return self._post(
            f"/session/{session_id}/summarize",
            {"providerID": provider_id, "modelID": model_id},
        )

    def revert_message(self, session_id: str, message_id: str, *, part_id: str | None = None) -> bool:
        """POST /session/:id/revert — revert a message."""
        body = {"messageID": message_id}
        if part_id is not None:
            body["partID"] = part_id
        return self._post(f"/session/{session_id}/revert", body)

    def unrevert_session(self, session_id: str) -> bool:
        """POST /session/:id/unrevert — restore all reverted messages."""
        return self._post(f"/session/{session_id}/unrevert", {})

    def respond_permission(self, session_id: str, permission_id: str, response: bool, *, remember: bool | None = None) -> bool:
        """POST /session/:id/permissions/:permissionID — respond to permission request."""
        body = {"response": response}
        if remember is not None:
            body["remember"] = remember
        return self._post(f"/session/{session_id}/permissions/{permission_id}", body)

    # ── Messages ─────────────────────────────────────────────────────────────

    def list_messages(self, session_id: str, *, limit: int | None = None) -> list[dict]:
        """GET /session/:id/message — list messages in session."""
        path = f"/session/{session_id}/message"
        if limit is not None:
            path += f"?limit={limit}"
        return self._get(path)

    def get_message(self, session_id: str, message_id: str) -> dict:
        """GET /session/:id/message/:messageID — get message details."""
        return self._get(f"/session/{session_id}/message/{message_id}")

    def send_message(
        self,
        session_id: str,
        content: str | list[dict],
        *,
        message_id: str | None = None,
        model: str | None = None,
        agent: str | None = None,
        no_reply: bool | None = None,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """
        POST /session/:id/message — send message and wait for response.
        content can be a string or a list of part blocks.
        """
        body: dict[str, Any] = {"parts": [{"type": "text", "text": content}] if isinstance(content, str) else content}
        if message_id is not None:
            body["messageID"] = message_id
        if model is not None:
            body["model"] = model
        if agent is not None:
            body["agent"] = agent
        if no_reply is not None:
            body["noReply"] = no_reply
        if system is not None:
            body["system"] = system
        if tools is not None:
            body["tools"] = tools
        return self._post(f"/session/{session_id}/message", body)

    def prompt_async(self, session_id: str, content: str | list[dict], **kwargs) -> None:
        """
        POST /session/:id/prompt_async — send message without waiting.
        Same signature as send_message but returns immediately (204).
        """
        body: dict[str, Any] = {"parts": [{"type": "text", "text": content}] if isinstance(content, str) else content}
        for key in ("messageID", "model", "agent", "noReply", "system", "tools"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]
        url = f"{self.base}/session/{session_id}/prompt_async"
        data = _json.dumps(body).encode("utf-8")
        req = _urlreq.Request(url, data=data, headers={"Content-Type": "application/json"})
        with _urlreq.urlopen(req, timeout=self.timeout) as resp:
            # 204 No Content — no body
            pass

    def execute_command(
        self,
        session_id: str,
        command: str,
        *,
        message_id: str | None = None,
        agent: str | None = None,
        model: str | None = None,
        arguments: dict | None = None,
    ) -> dict:
        """POST /session/:id/command — execute a slash command."""
        body: dict[str, Any] = {"command": command}
        if message_id is not None:
            body["messageID"] = message_id
        if agent is not None:
            body["agent"] = agent
        if model is not None:
            body["model"] = model
        if arguments is not None:
            body["arguments"] = arguments
        return self._post(f"/session/{session_id}/command", body)

    def shell(self, session_id: str, command: str, *, agent: str | None = None, model: str | None = None) -> dict:
        """POST /session/:id/shell — execute shell command."""
        body: dict[str, Any] = {"command": command}
        if agent is not None:
            body["agent"] = agent
        if model is not None:
            body["model"] = model
        return self._post(f"/session/{session_id}/shell", body)

    # ── Commands ─────────────────────────────────────────────────────────────

    def list_commands(self) -> list[dict]:
        """GET /command — list all commands."""
        return self._get("/command")

    # ── File find ────────────────────────────────────────────────────────────

    def find_text(self, pattern: str) -> list[dict]:
        """GET /find?pattern=<pat> — search text in files."""
        import urllib.parse
        encoded = urllib.parse.quote(pattern, safe="")
        return self._get(f"/find?pattern={encoded}")

    def find_file(self, query: str, *, type: str | None = None, directory: str | None = None, limit: int | None = None) -> list[str]:
        """GET /find/file?query=<q> — find files/dirs by name."""
        import urllib.parse
        params = [("query", query)]
        if type:
            params.append(("type", type))
        if directory:
            params.append(("directory", directory))
        if limit is not None:
            params.append(("limit", str(limit)))
        q = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params)
        return self._get(f"/find/file?{q}")

    def find_symbol(self, query: str) -> list[dict]:
        """GET /find/symbol?query=<q> — find workspace symbols."""
        import urllib.parse
        encoded = urllib.parse.quote(query, safe="")
        return self._get(f"/find/symbol?query={encoded}")

    # ── File tree ────────────────────────────────────────────────────────────

    def list_files(self, path: str = "/") -> dict:
        """GET /file?path=<p> — list files and directories."""
        import urllib.parse
        encoded = urllib.parse.quote(path, safe="")
        return self._get(f"/file?path={encoded}")

    def read_file(self, path: str) -> dict:
        """GET /file/content?path=<p> — read file content."""
        import urllib.parse
        encoded = urllib.parse.quote(path, safe="")
        return self._get(f"/file/content?path={encoded}")

    def file_status(self) -> list[dict]:
        """GET /file/status — get status of tracked files."""
        return self._get("/file/status")

    # ── Tools (experimental) ─────────────────────────────────────────────────

    def experimental_tool_ids(self) -> dict:
        """GET /experimental/tool/ids — list all tool IDs."""
        return self._get("/experimental/tool/ids")

    def experimental_tools(self, *, provider: str | None = None, model: str | None = None) -> dict:
        """GET /experimental/tool?provider=<p>&model=<m> — list tools with JSON Schema."""
        path = "/experimental/tool"
        params = []
        if provider:
            params.append(("provider", provider))
        if model:
            params.append(("model", model))
        if params:
            import urllib.parse
            q = "&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in params)
            path += f"?{q}"
        return self._get(path)

    # ── LSP / Formatter / MCP ────────────────────────────────────────────────

    def lsp_status(self) -> list[dict]:
        """GET /lsp — get LSP server status."""
        return self._get("/lsp")

    def formatter_status(self) -> list[dict]:
        """GET /formatter — get formatter tool status."""
        return self._get("/formatter")

    def mcp_status(self) -> dict:
        """GET /mcp — get MCP server status."""
        return self._get("/mcp")

    def add_mcp_server(self, name: str, config: dict) -> dict:
        """POST /mcp — dynamically add MCP server."""
        return self._post("/mcp", {"name": name, "config": config})

    # ── Agents ───────────────────────────────────────────────────────────────

    def list_agents(self) -> list[dict]:
        """GET /agent — list all available agents."""
        return self._get("/agent")

    # ── Log ──────────────────────────────────────────────────────────────────

    def write_log(self, service: str, level: str, message: str, *, extra: dict | None = None) -> bool:
        """POST /log — write a log entry."""
        body = {"service": service, "level": level, "message": message}
        if extra is not None:
            body["extra"] = extra
        return self._post("/log", body)

    # ── TUI ─────────────────────────────────────────────────────────────────

    def tui_append_prompt(self, text: str) -> bool:
        """POST /tui/append-prompt — append text to prompt."""
        return self._post("/tui/append-prompt", {"text": text})

    def tui_open_help(self) -> bool:
        """POST /tui/open-help — open help dialog."""
        return self._post("/tui/open-help", {})

    def tui_open_sessions(self) -> bool:
        """POST /tui/open-sessions — open session selector."""
        return self._post("/tui/open-sessions", {})

    def tui_open_themes(self) -> bool:
        """POST /tui/open-themes — open theme selector."""
        return self._post("/tui/open-themes", {})

    def tui_open_models(self) -> bool:
        """POST /tui/open-models — open model selector."""
        return self._post("/tui/open-models", {})

    def tui_submit_prompt(self) -> bool:
        """POST /tui/submit-prompt — submit current prompt."""
        return self._post("/tui/submit-prompt", {})

    def tui_clear_prompt(self) -> bool:
        """POST /tui/clear-prompt — clear current prompt."""
        return self._post("/tui/clear-prompt", {})

    def tui_execute_command(self, command: str) -> bool:
        """POST /tui/execute-command — execute a command."""
        return self._post("/tui/execute-command", {"command": command})

    def tui_show_toast(self, message: str, *, title: str | None = None, variant: str | None = None) -> bool:
        """POST /tui/show-toast — show toast notification."""
        body = {"message": message}
        if title is not None:
            body["title"] = title
        if variant is not None:
            body["variant"] = variant
        return self._post("/tui/show-toast", body)

    def tui_control_next(self) -> dict:
        """GET /tui/control/next — wait for next control request."""
        return self._get("/tui/control/next")

    def tui_control_response(self, body: dict) -> bool:
        """POST /tui/control/response — respond to control request."""
        return self._post("/tui/control/response", body)

    # ── Auth ─────────────────────────────────────────────────────────────────

    def set_auth(self, provider_id: str, credentials: dict) -> bool:
        """PUT /auth/:id — set authentication credentials."""
        url = f"{self.base}/auth/{provider_id}"
        data = _json.dumps(credentials).encode("utf-8")
        req = _urlreq.Request(url, data=data, method="PUT", headers={"Content-Type": "application/json"})
        with _urlreq.urlopen(req, timeout=self.timeout) as resp:
            return 200 <= resp.status < 300