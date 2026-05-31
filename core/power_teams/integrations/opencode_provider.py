"""
opencode_provider.py  —  Full hook class for opencode HTTP server
Covers every endpoint in the opencode OpenAPI spec.
Errors are logged to runtime/logs/opencode_errors.log.
"""

import json
import uuid
import logging
import os
import sys

# Force UTF-8 on Windows (PowerShell defaults to cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth


# ─────────────────────────────────────────────────────────────
#  LOGGING SETUP  (console INFO + file ERROR)
# ─────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_FILE = PROJECT_ROOT / "core" / "runtime" / "logs" / "opencode_errors.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

log = logging.getLogger("opencode_provider")
log.setLevel(logging.DEBUG)

if not log.handlers:
    # console — INFO and above
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setLevel(logging.INFO)
    _ch.setFormatter(_fmt)
    log.addHandler(_ch)

    # file — WARNING and above (errors go here)
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _fh.setLevel(logging.WARNING)
    _fh.setFormatter(_fmt)
    log.addHandler(_fh)


# ─────────────────────────────────────────────────────────────
#  EXCEPTIONS
# ─────────────────────────────────────────────────────────────

class OpencodeConnectionError(Exception):
    pass

class OpencodeRequestError(Exception):
    def __init__(self, method, path, status_code, body):
        self.method      = method
        self.path        = path
        self.status_code = status_code
        self.body        = body
        msg = f"{method} {path} -> HTTP {status_code}: {body[:300]}"
        log.error(msg)
        super().__init__(msg)

class OpencodeEmptyResponse(Exception):
    def __init__(self, path, model=None):
        msg = f"Empty response from {path}  model={model}"
        log.error(msg)
        super().__init__(msg)


# ─────────────────────────────────────────────────────────────
#  PROVIDER CLASS
# ─────────────────────────────────────────────────────────────

class OpencodeServeProvider:
    """
    Full HTTP hook for opencode server.
    Covers all endpoints in the OpenAPI spec.
    """

    def __init__(
        self,
        host:     str = "127.0.0.1",
        port:     int = 4096,
        username: str = "opencode",
        password: str = None,
        timeout:  int = 30,
        model:    str = None,
        agent:    str = None,
    ):
        self.host    = host
        self.port    = port
        self.base    = f"http://{host}:{port}"
        self.timeout = timeout
        self.model   = model
        self.agent   = agent

        self._http       = requests.Session()
        self._connected  = False
        self._version    = None

        # ── network health / queue ─────────────────────────────────
        # The dedicated health-check endpoint may live on a different port.
        self._health_url       = "http://localhost:18765/global/health"
        self._network_state    = "unknown"   # "healthy" | "degraded" | "offline"
        self._message_queue     = []          # queue of (session_id, text, model, agent, kwargs)
        self._queue_processor   = False

        if password:
            self._http.auth = HTTPBasicAuth(username, password)

        log.info(f"OpencodeServeProvider init -> {self.base}  model={model}")

    # ── internals ───────────────────────────────────────────

    def _url(self, path):
        return f"{self.base}{path}"

    def _get(self, path, **kw):
        log.debug(f"GET {path}")
        try:
            return self._http.get(self._url(path), timeout=self.timeout, **kw)
        except requests.ConnectionError as e:
            log.error(f"Connection error on GET {path}: {e}")
            raise OpencodeConnectionError(f"GET {path} failed: {e}") from e

    def _post(self, path, body=None, timeout=None, **kw):
        log.debug(f"POST {path}  {str(body)[:80] if body else ''}")
        try:
            return self._http.post(
                self._url(path), json=body,
                timeout=timeout or self.timeout, **kw
            )
        except requests.ConnectionError as e:
            log.error(f"Connection error on POST {path}: {e}")
            raise OpencodeConnectionError(f"POST {path} failed: {e}") from e

    def _patch(self, path, body=None):
        log.debug(f"PATCH {path}")
        try:
            return self._http.patch(self._url(path), json=body, timeout=self.timeout)
        except requests.ConnectionError as e:
            log.error(f"Connection error on PATCH {path}: {e}")
            raise OpencodeConnectionError(str(e)) from e

    def _delete(self, path):
        log.debug(f"DELETE {path}")
        try:
            return self._http.delete(self._url(path), timeout=self.timeout)
        except requests.ConnectionError as e:
            log.error(f"Connection error on DELETE {path}: {e}")
            raise OpencodeConnectionError(str(e)) from e

    def _put(self, path, body=None):
        log.debug(f"PUT {path}")
        try:
            return self._http.put(self._url(path), json=body, timeout=self.timeout)
        except requests.ConnectionError as e:
            log.error(f"PUT {path} failed: {e}")
            raise OpencodeConnectionError(str(e)) from e

    def _check(self, r, method="?"):
        """Raise OpencodeRequestError if not 2xx."""
        if not r.ok:
            raise OpencodeRequestError(method, r.url, r.status_code, r.text)
        return r

    def _json(self, r, method="?"):
        self._check(r, method)
        return r.json()

    def _stream_body(self, r):
        """Read chunked / streaming response body."""
        chunks = []
        for chunk in r.iter_content(chunk_size=None):
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _msg_id():
        return f"msg_{uuid.uuid4().hex}"

    # ── connection ──────────────────────────────────────────

    def connect(self) -> dict:
        """Health check. Raises OpencodeConnectionError if unreachable."""
        try:
            r = self._get("/global/health")
            data = self._json(r, "GET")
            self._connected = data.get("healthy", False)
            self._version   = data.get("version")
            log.info(f"Connected -> opencode {self._version}")
            return data
        except OpencodeConnectionError:
            log.error(f"Cannot connect to {self.base}")
            raise

    @property
    def is_connected(self): return self._connected

    @property
    def version(self):      return self._version

    @property
    def network_state(self): return self._network_state

    # ── network health ───────────────────────────────────────────

    def check_network_health(self) -> str:
        """
        Ping the dedicated health-check endpoint and classify response time.

        Returns
        -------
        str
            "healthy"  : response < 500 ms
            "degraded" : response 500 ms – 2000 ms
            "offline"  : timeout / error after 2 s
        """
        import time as _time

        try:
            start = _time.monotonic()
            r = self._http.get(self._health_url, timeout=2)
            elapsed_ms = (_time.monotonic() - start) * 1000
            r.raise_for_status()
            prev = self._network_state
            if elapsed_ms < 500:
                self._network_state = "healthy"
            elif elapsed_ms <= 2000:
                self._network_state = "degraded"
            else:
                self._network_state = "offline"
            if prev != self._network_state:
                log.warning(f"Network: {prev} -> {self._network_state}  ({elapsed_ms:.0f} ms)")
            return self._network_state
        except Exception as e:
            prev = self._network_state
            self._network_state = "offline"
            if prev != "offline":
                log.error(f"Network: {prev} -> offline, queuing messages  ({e})")
            return "offline"

    # ── global ──────────────────────────────────────────────

    def health(self) -> dict:
        return self._json(self._get("/global/health"), "GET")

    def global_events(self, callback, timeout=300):
        """SSE stream from /global/event."""
        self._sse_stream("/global/event", callback, timeout)

    # ── project ─────────────────────────────────────────────

    def list_projects(self) -> list:
        return self._json(self._get("/project"), "GET")

    def current_project(self) -> dict:
        return self._json(self._get("/project/current"), "GET")

    # ── path / vcs ──────────────────────────────────────────

    def get_path(self) -> dict:
        return self._json(self._get("/path"), "GET")

    def get_vcs(self) -> dict:
        return self._json(self._get("/vcs"), "GET")

    # ── instance ────────────────────────────────────────────

    def dispose_instance(self) -> bool:
        return self._json(self._post("/instance/dispose"), "POST")

    # ── config ──────────────────────────────────────────────

    def get_config(self) -> dict:
        return self._json(self._get("/config"), "GET")

    def update_config(self, patch: dict) -> dict:
        return self._json(self._patch("/config", patch), "PATCH")

    def get_config_providers(self) -> dict:
        return self._json(self._get("/config/providers"), "GET")

    # ── providers ───────────────────────────────────────────

    def list_providers(self) -> dict:
        return self._json(self._get("/provider"), "GET")

    def connected_providers(self) -> list:
        return self.list_providers().get("connected", [])

    def list_models(self, provider_id: str = None) -> list:
        """Return list of (providerID, modelID) tuples."""
        data  = self.list_providers()
        pairs = []
        for p in data.get("all", []):
            pid = p.get("id", "")
            if provider_id and pid != provider_id:
                continue
            for mid in p.get("models", {}).keys():
                pairs.append((pid, mid))
        return pairs

    def default_model_string(self) -> str | None:
        """Return best available model as 'providerID/modelID'."""
        data      = self.list_providers()
        connected = set(data.get("connected", []))
        defaults  = data.get("default", {})
        for p in data.get("all", []):
            pid = p.get("id", "")
            if pid in connected:
                models = list(p.get("models", {}).keys())
                if models:
                    return f"{pid}/{models[0]}"
        for pid, mid in defaults.items():
            return f"{pid}/{mid}"
        return None

    def get_provider_auth(self) -> dict:
        return self._json(self._get("/provider/auth"), "GET")

    def oauth_authorize(self, provider_id: str) -> dict:
        return self._json(self._post(f"/provider/{provider_id}/oauth/authorize"), "POST")

    def oauth_callback(self, provider_id: str) -> bool:
        return self._json(self._post(f"/provider/{provider_id}/oauth/callback"), "POST")

    def set_auth(self, provider_id: str, credentials: dict) -> bool:
        return self._json(self._put(f"/auth/{provider_id}", credentials), "PUT")

    # ── sessions ────────────────────────────────────────────

    def create_session(self, title: str = "", parent_id: str = None) -> dict:
        body = {}
        if title:     body["title"]    = title
        if parent_id: body["parentID"] = parent_id
        r = self._json(self._post("/session", body), "POST")
        log.info(f"Session created: {r.get('id')}  title={title}")
        return r

    def list_sessions(self, limit: int = None) -> list:
        sessions = self._json(self._get("/session"), "GET")
        return sessions[:limit] if limit else sessions

    def session_status(self) -> dict:
        return self._json(self._get("/session/status"), "GET")

    def get_session(self, session_id: str) -> dict:
        return self._json(self._get(f"/session/{session_id}"), "GET")

    def update_session(self, session_id: str, title: str) -> dict:
        return self._json(self._patch(f"/session/{session_id}", {"title": title}), "PATCH")

    def delete_session(self, session_id: str) -> bool:
        r = self._json(self._delete(f"/session/{session_id}"), "DELETE")
        log.info(f"Session deleted: {session_id}")
        return r

    def session_children(self, session_id: str) -> list:
        return self._json(self._get(f"/session/{session_id}/children"), "GET")

    def session_todo(self, session_id: str) -> list:
        return self._json(self._get(f"/session/{session_id}/todo"), "GET")

    def init_session(self, session_id: str, message_id: str,
                     provider_id: str, model_id: str) -> bool:
        body = {"messageID": message_id, "providerID": provider_id, "modelID": model_id}
        return self._json(self._post(f"/session/{session_id}/init", body), "POST")

    def fork_session(self, session_id: str, message_id: str = None) -> dict:
        body = {}
        if message_id: body["messageID"] = message_id
        return self._json(self._post(f"/session/{session_id}/fork", body), "POST")

    def abort_session(self, session_id: str) -> bool:
        return self._json(self._post(f"/session/{session_id}/abort"), "POST")

    def share_session(self, session_id: str) -> dict:
        return self._json(self._post(f"/session/{session_id}/share"), "POST")

    def unshare_session(self, session_id: str) -> dict:
        return self._json(self._delete(f"/session/{session_id}/share"), "DELETE")

    def session_diff(self, session_id: str, message_id: str = None) -> list:
        path = f"/session/{session_id}/diff"
        if message_id: path += f"?messageID={message_id}"
        return self._json(self._get(path), "GET")

    def summarize_session(self, session_id: str, provider_id: str, model_id: str) -> bool:
        body = {"providerID": provider_id, "modelID": model_id}
        return self._json(self._post(f"/session/{session_id}/summarize", body), "POST")

    def revert_message(self, session_id: str, message_id: str, part_id: str = None) -> bool:
        body = {"messageID": message_id}
        if part_id: body["partID"] = part_id
        return self._json(self._post(f"/session/{session_id}/revert", body), "POST")

    def unrevert_session(self, session_id: str) -> bool:
        return self._json(self._post(f"/session/{session_id}/unrevert"), "POST")

    def respond_permission(self, session_id: str, permission_id: str,
                           response: str, remember: bool = False) -> bool:
        body = {"response": response, "remember": remember}
        return self._json(
            self._post(f"/session/{session_id}/permissions/{permission_id}", body), "POST"
        )

    def list_questions(self) -> list:
        """Return pending question requests."""
        return self._json(self._get("/question"), "GET")

    def reply_question(self, request_id: str, answers: list) -> bool:
        """
        Reply to a question request.
        answers must be a list of answer lists, e.g. [["Python 3.11"], ["Yes"]].
        """
        return self._json(
            self._post(f"/question/{request_id}/reply", {"answers": answers}), "POST"
        )

    def reject_question(self, request_id: str) -> bool:
        """Reject a pending question request."""
        return self._json(self._post(f"/question/{request_id}/reject"), "POST")

    # ── messages ────────────────────────────────────────────

    def send_message(
        self,
        session_id:  str,
        text:        str,
        model:       str = None,
        agent:       str = None,
        message_id:  str = None,
        no_reply:    bool = False,
        system:      str = None,
        timeout:     int = 120,
        on_delta:    callable = None,  # on_delta(part_type, chunk) for live streaming
        on_question: callable = None,   # on_question(request) -> list[list[str]] or None
    ) -> dict:
        """
        Send a message via prompt_async, then collect the reply via SSE /event stream.
        Matches the telegram-bot pattern: fire-and-forget + event subscription.
        on_delta(part_type, chunk) is called for each streaming text/reasoning chunk.
        """
        mid  = message_id or self._msg_id()
        body = {
            "messageID": mid,
            "parts":     [{"type": "text", "text": text}],
        }
        m = model or self.model
        a = agent or self.agent
        if m:
            if isinstance(m, str) and "/" in m:
                pid, mid_id = m.split("/", 1)
                body["model"] = {"providerID": pid, "modelID": mid_id}
            elif isinstance(m, dict):
                body["model"] = m
        if a:        body["agent"]   = a
        if no_reply: body["noReply"] = True
        if system:   body["system"]  = system

        log.info(f"send_message -> {session_id[:12]}  model={m}  [{text[:50]}]")
        log.debug(f"send_message body: {json.dumps(body)}")

        health = self.check_network_health()
        if health == "offline":
            self._message_queue.append(("sync", session_id, text, m, a, dict(
                no_reply=no_reply, system=system, timeout=timeout,
                on_delta=on_delta, on_question=on_question,
            )))
            log.warning(f"send_message queued (offline)  session={session_id[:12]}  qlen={len(self._message_queue)}")
            return {"status": "queued", "messageID": mid}

        if health == "degraded":
            timeout = int(timeout * 1.5)
            log.info(f"send_message degraded mode  timeout={timeout}s")

        r = self._post(f"/session/{session_id}/prompt_async", body)
        self._check(r, "POST")
        log.debug(f"prompt_async accepted  messageID={mid[:16]}")

        # ── Step 2: collect reply via SSE /event ───────────────
        return self._await_reply_sse(session_id, mid, timeout, on_delta=on_delta, on_question=on_question)

    # ── private: SSE reply collector ────────────────────────────

    def _await_reply_sse(
        self,
        session_id:  str,
        message_id:  str,
        timeout:     int,
        on_delta:    callable = None,   # on_delta(part_type: str, chunk: str)
        on_question: callable = None,    # on_question(request: dict) -> list[list[str]] or None
    ) -> dict:
        """
        Subscribe to GET /event (SSE) and collect parts for message_id.

        Completion signals (in order of preference):
          1. message.updated  where properties.info.time.completed is set
          2. message.part.updated  where part.type == "step-finish"

        Delta accumulation:
          • message.part.delta  -> append chunk  (safe, never overwrite)
          • message.part.updated -> only used if NO deltas received for that part
            (guards against out-of-order events overwriting accumulated text)

        on_delta(part_type, chunk) is called for every streaming text/reasoning chunk.
        """
        import time as _time

        text_parts      = {}    # part_id -> {"type": str, "text": str}
        parts_w_deltas  = set() # pids that received ≥1 true delta event
        parts_streamed  = {}    # part_id -> chars already sent to on_delta
        tool_by_callid  = {}    # callID -> {"tool", "input", "output", "status"}
        finish_info     = {}
        saw_final_assistant = False
        done            = False
        start           = _time.monotonic()
        events_seen     = 0
        handled_questions = set()

        def _emit_delta(ptype: str, pid: str, full_text: str):
            """Compute new suffix vs what was already streamed, call on_delta."""
            if not on_delta or not full_text:
                return
            already = parts_streamed.get(pid, "")
            if full_text.startswith(already):
                chunk = full_text[len(already):]
            else:
                chunk = full_text   # rare: text was rewritten
            if chunk:
                parts_streamed[pid] = full_text
                try:
                    on_delta(ptype, chunk)
                except Exception:
                    pass

        def _handle_question_request(request: dict):
            qid = request.get("id")
            if not qid or qid in handled_questions:
                return False
            if request.get("sessionID") != session_id:
                return False
            handled_questions.add(qid)
            if on_question:
                try:
                    answers = on_question(request)
                    if answers is None:
                        self.reject_question(qid)
                    else:
                        self.reply_question(qid, answers)
                except Exception as e:
                    log.error(f"question handler failed: {e}")
            else:
                log.warning(f"question requested but no handler installed: {qid}")
                # Auto-reject so opencode does not hang waiting for an answer.
                try:
                    self.reject_question(qid)
                    log.warning(f"auto-rejected question {qid}")
                except Exception as _qe:
                    log.error(f"auto-reject failed for {qid}: {_qe}")
            return True

        def _poll_pending_questions():
            if not on_question:
                return 0
            count = 0
            try:
                for request in self.list_questions():
                    if _handle_question_request(request):
                        count += 1
            except Exception as e:
                log.debug(f"question poll failed: {e}")
            return count

        def on_event(etype: str, data):
            nonlocal done, finish_info, events_seen, saw_final_assistant, start

            if done:
                return False
            if _time.monotonic() - start > timeout:
                if _poll_pending_questions():
                    start = _time.monotonic()
                    return True
                log.warning(f"_await_reply_sse timeout after {timeout}s  mid={message_id[:16]}")
                return False
            if not isinstance(data, dict):
                return True

            events_seen += 1
            evt   = data.get("type") or etype or ""
            props = data.get("properties") or {}

            def _g(key):
                return props.get(key) or data.get(key)

            part_obj = props.get("part") or {}
            info_obj = props.get("info") or {}

            # sessionID: check props, info, and part
            sid = (_g("sessionID")
                   or info_obj.get("sessionID")
                   or part_obj.get("sessionID"))

            # filter by session only — assistant reply has a DIFFERENT messageID
            # than the user message we sent, so never filter by messageID on parts
            if sid and sid != session_id:
                return True

            log.debug(f"SSE [{events_seen:02d}] {evt!r}  sid={str(sid)[:12] if sid else '-'}  done={done}  parts_so_far={len(text_parts)}")

            if evt == "question.asked":
                _handle_question_request(props)
                return True

            # ── true streaming delta (e.g. opencode/big-pickle) ───
            if evt == "message.part.delta":
                part  = props.get("part") or {}
                pid   = part.get("id") or _g("partID") or "d0"
                # ptype from part metadata, NOT from event type
                ptype = part.get("type") or props.get("type") or "text"
                # do NOT fall back to data["type"] here — that would give "message.part.delta"
                chunk = _g("delta") or part.get("text") or ""
                if pid not in text_parts:
                    text_parts[pid] = {"type": ptype, "text": ""}
                text_parts[pid]["text"] += chunk
                parts_w_deltas.add(pid)
                if chunk and on_delta:
                    parts_streamed[pid] = text_parts[pid]["text"]
                    try:
                        on_delta(ptype, chunk)
                    except Exception:
                        pass

            # ── progressive snapshot (e.g. MiniMax-M2.7) ─────────
            # Each event carries the FULL text so far for that part.
            # We diff vs what was already streamed -> emit only new suffix.
            elif evt == "message.part.updated":
                part  = props.get("part") or part_obj or props
                pid   = part.get("id") or "u0"
                ptype = part.get("type") or "text"
                ptxt  = part.get("text") or part.get("reasoning") or ""

                log.debug(f"  part.updated pid={str(pid)[:12]}  type={ptype!r}  ptxt_len={len(ptxt)}")

                if ptype == "step-finish":
                    finish_info = {
                        "reason": part.get("reason"),
                        "tokens": part.get("tokens", {}),
                        "cost":   part.get("cost", 0),
                    }
                    log.debug(f"  step-finish (continuing)  reason={finish_info.get('reason')}")
                    return True  # keep listening

                # ── tool call tracking ─────────────────────────
                if ptype == "tool":
                    cid   = part.get("callID", pid)
                    state = part.get("state") or {}
                    tool_name = part.get("tool", "?")
                    status = state.get("status", "")
                    if cid not in tool_by_callid:
                        tool_by_callid[cid] = {
                            "tool":   tool_name,
                            "input":  state.get("input", {}),
                            "output": "",
                            "status": status,
                            "metadata": {},
                        }
                    else:
                        tool_by_callid[cid]["status"] = status
                        if state.get("input"):
                            tool_by_callid[cid]["input"] = state["input"]

                    # capture output from metadata or result
                    meta   = state.get("metadata") or {}
                    if meta:
                        tool_by_callid[cid]["metadata"] = meta
                    output = meta.get("output") or state.get("result") or ""
                    if output:
                        tool_by_callid[cid]["output"] = str(output).rstrip()

                    # stream tool label on first appearance
                    if on_delta and status in ("running", "") and not tool_by_callid[cid].get("_announced"):
                        tool_by_callid[cid]["_announced"] = True
                        tool_input = state.get("input") or {}
                        if isinstance(tool_input, dict):
                            detail = (
                                tool_input.get("command")
                                or tool_input.get("filePath")
                                or tool_input.get("path")
                                or tool_input.get("pattern")
                                or tool_input.get("description")
                                or ""
                            )
                            if not detail and tool_input:
                                detail = json.dumps(tool_input, ensure_ascii=False)
                        else:
                            detail = str(tool_input)
                        detail = str(detail)[:120]
                        try:
                            on_delta("tool", f"\n[tool: {tool_name}]  {detail}\n")
                        except Exception:
                            pass

                    # stream output when completed
                    if on_delta and status == "completed" and output:
                        try:
                            on_delta("tool_result", f"[result]: {output}\n")
                        except Exception:
                            pass
                    return True

                if ptxt and pid not in parts_w_deltas:
                    _emit_delta(ptype, pid, ptxt)
                    text_parts[pid] = {"type": ptype, "text": ptxt}

            # ── ONLY completion signal: message.updated + time.completed ──
            # Fires once after ALL steps (including tool calls) are done.
            elif evt == "message.updated":
                info     = info_obj
                time_obj = info.get("time") or {}
                log.debug(f"  -> message.updated role={info.get('role')} time={time_obj}")
                if info.get("role") == "assistant" and time_obj.get("completed"):
                    reason = finish_info.get("reason") or info.get("reason") or "stop"
                    finish_info.update({
                        "reason": reason,
                        "tokens": info.get("tokens", {}),
                        "cost":   info.get("cost", 0),
                    })
                    log.debug(f"message completed  reason={reason} tokens={finish_info.get('tokens')}")
                    if reason == "tool-calls":
                        return True
                    saw_final_assistant = True
                    done = True
                    return False

            elif evt == "session.status":
                status = props.get("status") or {}
                if _g("sessionID") == session_id and status.get("type") == "idle":
                    log.debug("session idle")
                    done = True
                    return False

            elif evt in ("server.connected", "server.heartbeat"):
                _poll_pending_questions()

            return True

        # Bug 3: 指數退避重試 — timeout 後不直接放棄
        # 等待間隔: 5s → 10s → 20s，最多 3 次重試
        _sse_max_retries = 3
        _sse_backoff = [5, 10, 20]
        _sse_retry = 0

        while True:
            try:
                self._sse_stream("/event", on_event, timeout + 5)
            except Exception as e:
                if not done:
                    log.error(f"SSE stream error while awaiting reply: {e}")

            # 若已完成或有部分結果，跳出重試迴圈
            if done or text_parts:
                break

            # 超過重試次數上限 — 放棄
            if _sse_retry >= _sse_max_retries:
                log.error(f"_await_reply_sse: giving up after {_sse_max_retries} retries  mid={message_id[:16]}")
                break

            wait_s = _sse_backoff[_sse_retry]
            log.warning(
                f"_await_reply_sse: SSE timeout/no-result "
                f"(retry {_sse_retry + 1}/{_sse_max_retries}), waiting {wait_s}s  mid={message_id[:16]}"
            )
            _time.sleep(wait_s)
            # 重置狀態，為下一次 SSE 連接做準備
            done = False
            start = _time.monotonic()
            _sse_retry += 1

        elapsed = _time.monotonic() - start
        log.info(f"send_message ✓  {events_seen} events  "
                 f"{len(text_parts)} parts  {elapsed:.1f}s")

        if not text_parts and not done:
            raise OpencodeEmptyResponse(f"/event session={session_id}", message_id)

        parts = [
            {"type": v["type"], "text": v["text"]}
            for v in text_parts.values()
            if v.get("text")
        ]
        if finish_info:
            parts.append({"type": "step-finish", **finish_info})

        # clean internal flag before returning
        tool_calls = []
        for tc in tool_by_callid.values():
            tc_clean = {k: v for k, v in tc.items() if k != "_announced"}
            tool_calls.append(tc_clean)

        return {
            "parts":      parts,
            "tool_calls": tool_calls,
            "id":         message_id,
            "sessionID":  session_id,
        }

    def send_message_async(
        self,
        session_id:  str,
        text:        str,
        model:       str = None,
        agent:       str = None,
        message_id:  str = None,
    ) -> str:
        """Fire prompt_async and return immediately. Returns messageID."""
        mid  = message_id or self._msg_id()
        body = {"messageID": mid, "parts": [{"type": "text", "text": text}]}
        m = model or self.model
        a = agent or self.agent
        if m:
            if isinstance(m, str) and "/" in m:
                pid, mid_id = m.split("/", 1)
                body["model"] = {"providerID": pid, "modelID": mid_id}
            elif isinstance(m, dict):
                body["model"] = m
        if a: body["agent"] = a

        health = self.check_network_health()
        if health == "offline":
            self._message_queue.append(("async", session_id, text, m, a, {}))
            log.warning(f"send_message_async queued (offline)  session={session_id[:12]}  qlen={len(self._message_queue)}")
            return mid

        if health == "degraded":
            log.info("send_message_async degraded mode")

        r = self._post(f"/session/{session_id}/prompt_async", body)
        self._check(r, "POST")
        log.info(f"send_message_async -> {mid}")
        return mid

    def list_messages(self, session_id: str, limit: int = None) -> list:
        path = f"/session/{session_id}/message"
        if limit: path += f"?limit={limit}"
        return self._json(self._get(path), "GET")

    def get_message(self, session_id: str, message_id: str) -> dict:
        return self._json(self._get(f"/session/{session_id}/message/{message_id}"), "GET")

    def send_command(self, session_id: str, command: str, arguments: str = "",
                     model: str = None, agent: str = None,
                     message_id: str = None) -> dict:
        body = {
            "messageID": message_id or self._msg_id(),
            "command":   command,
            "arguments": arguments,
        }
        m = model or self.model
        a = agent or self.agent
        if m: body["model"] = m
        if a: body["agent"] = a
        return self._json(self._post(f"/session/{session_id}/command", body), "POST")

    def run_shell(self, session_id: str, command: str,
                  agent: str = None, model: str = None) -> dict:
        body = {"command": command, "agent": agent or self.agent or ""}
        m = model or self.model
        if m: body["model"] = m
        return self._json(self._post(f"/session/{session_id}/shell", body), "POST")

    @staticmethod
    def extract_text(message: dict) -> str:
        """Extract plain text from { info, parts } message dict."""
        parts = message.get("parts", [])
        return "\n".join(
            p.get("text", "")
            for p in parts
            if p.get("type") == "text" and p.get("text")
        )

    # ── commands ────────────────────────────────────────────

    def list_commands(self) -> list:
        return self._json(self._get("/command"), "GET")

    # ── files & search ──────────────────────────────────────

    def find_text(self, pattern: str) -> list:
        return self._json(self._get(f"/find?pattern={pattern}"), "GET")

    def find_file(self, query: str, type_filter: str = None,
                  directory: str = None, limit: int = 20) -> list:
        params = f"query={query}&limit={limit}"
        if type_filter: params += f"&type={type_filter}"
        if directory:   params += f"&directory={directory}"
        return self._json(self._get(f"/find/file?{params}"), "GET")

    def find_symbol(self, query: str) -> list:
        return self._json(self._get(f"/find/symbol?query={query}"), "GET")

    def list_files(self, path: str = "") -> list:
        p = f"/file?path={path}" if path else "/file"
        return self._json(self._get(p), "GET")

    def read_file(self, path: str) -> dict:
        return self._json(self._get(f"/file/content?path={path}"), "GET")

    def file_status(self) -> list:
        return self._json(self._get("/file/status"), "GET")

    # ── tools (experimental) ────────────────────────────────

    def tool_ids(self) -> dict:
        return self._json(self._get("/experimental/tool/ids"), "GET")

    def list_tools(self, provider: str, model: str) -> dict:
        return self._json(
            self._get(f"/experimental/tool?provider={provider}&model={model}"), "GET"
        )

    # ── lsp / formatter / mcp ───────────────────────────────

    def lsp_status(self) -> list:
        return self._json(self._get("/lsp"), "GET")

    def formatter_status(self) -> list:
        return self._json(self._get("/formatter"), "GET")

    def list_mcp(self) -> dict:
        return self._json(self._get("/mcp"), "GET")

    def add_mcp(self, name: str, config: dict) -> dict:
        return self._json(self._post("/mcp", {"name": name, "config": config}), "POST")

    # ── agents ──────────────────────────────────────────────

    def list_agents(self) -> list:
        return self._json(self._get("/agent"), "GET")

    # ── logging ─────────────────────────────────────────────

    def write_log(self, service: str, level: str, message: str, extra: dict = None) -> bool:
        body = {"service": service, "level": level, "message": message}
        if extra: body["extra"] = extra
        return self._json(self._post("/log", body), "POST")

    # ── TUI ─────────────────────────────────────────────────

    def tui_append_prompt(self, text: str) -> bool:
        return self._json(self._post("/tui/append-prompt", {"text": text}), "POST")

    def tui_submit_prompt(self) -> bool:
        return self._json(self._post("/tui/submit-prompt"), "POST")

    def tui_clear_prompt(self) -> bool:
        return self._json(self._post("/tui/clear-prompt"), "POST")

    def tui_show_toast(self, message: str, title: str = None, variant: str = "info") -> bool:
        body = {"message": message, "variant": variant}
        if title: body["title"] = title
        return self._json(self._post("/tui/show-toast", body), "POST")

    def tui_execute_command(self, command: str) -> bool:
        return self._json(self._post("/tui/execute-command", {"command": command}), "POST")

    def tui_open_sessions(self) -> bool:
        return self._json(self._post("/tui/open-sessions"), "POST")

    def tui_open_models(self) -> bool:
        return self._json(self._post("/tui/open-models"), "POST")

    def tui_open_themes(self) -> bool:
        return self._json(self._post("/tui/open-themes"), "POST")

    def tui_open_help(self) -> bool:
        return self._json(self._post("/tui/open-help"), "POST")

    # ── events (SSE) ────────────────────────────────────────

    def stream_events(self, callback, timeout: int = 300):
        """
        Subscribe to /event SSE stream.
        callback(event_type: str, data: dict) -> return False to stop.
        """
        self._sse_stream("/event", callback, timeout)

    def _sse_stream(self, path: str, callback, timeout: int):
        try:
            r = self._http.get(self._url(path), stream=True, timeout=timeout)
            self._check(r, "GET")
            event_type = None
            for line in r.iter_lines(decode_unicode=True):
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        data = json.loads(raw)
                    except Exception:
                        data = raw
                    try:
                        keep = callback(event_type, data)
                    except Exception as e:
                        log.error(f"SSE callback error: {e}")
                        keep = True
                    if keep is False:
                        break
                elif not line:
                    event_type = None
        except Exception as e:
            log.error(f"SSE stream error on {path}: {e}")
            raise

    # ── doc ─────────────────────────────────────────────────

    def get_openapi_spec(self) -> str:
        """Return the raw OpenAPI spec HTML/JSON from /doc."""
        r = self._get("/doc")
        self._check(r, "GET")
        return r.text

    # ── convenience ─────────────────────────────────────────

    def quick_ask(self, prompt: str, title: str = None, timeout: int = 120) -> str:
        """One-shot: create session -> send -> return text -> delete."""
        model   = self.model or self.default_model_string()
        session = self.create_session(title or prompt[:40])
        sid     = session["id"]
        try:
            reply = self.send_message(sid, prompt, model=model, timeout=timeout)
            return self.extract_text(reply)
        except Exception as e:
            log.error(f"quick_ask failed: {e}")
            raise
        finally:
            try:
                self.delete_session(sid)
            except Exception:
                pass

    def __repr__(self):
        status = f"v{self._version}" if self._connected else "not connected"
        return f"OpencodeServeProvider({self.base}  {status}  model={self.model})"


# ─────────────────────────────────────────────────────────────
#  SMOKE TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.getLogger("opencode_provider").setLevel(logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument("--port",  type=int, default=4096)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    p = OpencodeServeProvider(port=args.port, model=args.model)

    print("── connect ──")
    print(p.connect())

    print("\n── providers ──")
    print("connected :", p.connected_providers())
    print("default   :", p.default_model_string())

    print("\n── agents ──")
    for a in p.list_agents()[:5]:
        print(" •", a.get("name") or a.get("id"))

    print("\n── mcp ──")
    for name, status in p.list_mcp().items():
        print(f" • {name}: {status}")

    print("\n── sessions (last 3) ──")
    for s in p.list_sessions(3):
        print(f" • {s['id'][:16]}  {s.get('title','')}")

    print(f"\nError log -> {LOG_FILE}")
