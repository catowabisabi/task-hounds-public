import { useState } from "react";
import { apiPost } from "../../../lib/api";
import type { ManagerMessage } from "../../../lib/api";
import { FullscreenMarkdownModal } from "./FullscreenMarkdownModal";

interface MessagesPanelProps {
  messages: ManagerMessage[];
  onRefresh: () => void;
}

export function MessagesPanel({ messages, onRefresh }: MessagesPanelProps) {
  const [modal, setModal] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [saved, setSaved] = useState("");

  const send = async (text: string) => {
    if (!text.trim()) return;
    setSending(true);
    setError("");
    setSaved("");
    try {
      await apiPost("/api/manager-messages", { content: text });
      setDraft("");
      setSaved("Queued for manager revision");
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--blue)" }}>Messages to Manager</p>
        <button onClick={() => setModal(true)} className="text-[11px] px-1.5 py-0.5 rounded transition-colors" style={{ color: "var(--text-dim)", border: "1px solid var(--border)" }} onMouseEnter={e => (e.currentTarget.style.color = "var(--blue)")} onMouseLeave={e => (e.currentTarget.style.color = "var(--text-dim)")}>⤢</button>
      </div>
      <div className="space-y-1 max-h-24 overflow-y-auto">
        {messages.length === 0
          ? <p className="text-[11px] italic" style={{ color: "var(--text-dim)" }}>No messages</p>
          : messages.slice(-5).map(m => (
            <div key={m.id} className="text-[11px] rounded p-1.5 whitespace-pre-wrap" style={{ background: "var(--bg-panel)", color: "var(--text-secondary)", border: "1px solid var(--border-dim)" }}>{m.content}</div>
          ))
        }
        </div>
      {error && <p className="text-[10px]" style={{ color: "var(--red)" }}>{error}</p>}
      {saved && <p className="text-[10px]" style={{ color: "var(--green)" }}>{saved}. Press Start Loop to get a manager response.</p>}
      <div className="flex gap-1">
        <input className="flex-1 rounded px-2 py-1 text-[12px] outline-none" style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text-primary)" }} placeholder="Quick message..." value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => e.key === "Enter" && send(draft)} onFocus={e => (e.target.style.borderColor = "var(--blue)")} onBlur={e => (e.target.style.borderColor = "var(--border)")} />
        <button onClick={() => send(draft)} disabled={sending || !draft.trim()} className="px-2 py-1 text-[11px] rounded disabled:opacity-40" style={{ background: "var(--bg-panel)", color: "var(--blue)", border: "1px solid var(--blue-dim)" }}>{sending ? "..." : "Send"}</button>
      </div>
      {modal && <FullscreenMarkdownModal title="Message to Manager" value="" onSave={send} onClose={() => setModal(false)} accent="var(--blue)" />}
    </div>
  );
}
