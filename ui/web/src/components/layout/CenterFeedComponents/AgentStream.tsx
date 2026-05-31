import { useStream } from "../../../hooks/useStream";
import { StateBadge } from "../../ui/Badge";
import { StreamView } from "../../ui/StreamView";
import { apiPost } from "../../../lib/api";
import type { Agent } from "../../../lib/api";
import { TimerDisplay } from "./TimerDisplay";

export function AgentStream({ agent, onClear, onStop }: {
  agent: Agent;
  onClear: () => void;
  onStop: () => void;
}) {
  const content = useStream(agent.name);

  const handleClear = async () => {
    await apiPost(`/api/stream/${agent.name}/clear`);
    onClear();
  };

  const handleStop = async () => {
    await apiPost(`/api/agents/${agent.name}/kill`);
    await apiPost(`/api/stream/${agent.name}/clear`);
    onStop();
  };

  const handleRestart = async () => {
    await apiPost(`/api/worker/restart`);
    onStop();
  };

  const isCrashed = agent.state === "error";
  const isBusy = agent.state === "busy";
  const errorText = agent.last_error?.trim();

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div
        className="flex items-center gap-2 px-4 py-2 shrink-0 flex-wrap"
        style={{ background: "var(--bg-panel)", borderBottom: "1px solid var(--border)" }}
      >
        <StateBadge state={agent.state as "idle" | "busy" | "waiting" | "error" | "offline"} />
        {isBusy && (
          <span className="text-[11px] animate-pulse" style={{ color: "var(--amber)" }}>working...</span>
        )}
        {isCrashed && (
          <span className="text-[11px]" style={{ color: "var(--red)" }}>
            {errorText ? "error" : "crashed"}
          </span>
        )}
        <TimerDisplay agentName={agent.name} />
        <div className="ml-auto flex gap-1">
          {agent.name === "worker" && (
            <button
              onClick={handleRestart}
              className="px-2 py-1 text-[10px] rounded transition-colors duration-200"
              style={{ background: "var(--green-bg)", color: "var(--green)", border: "1px solid var(--green-dim)" }}
            >
              Restart Worker
            </button>
          )}
          <button
            onClick={handleStop}
            className="px-2 py-1 text-[10px] rounded transition-colors duration-200"
            style={{ background: "var(--red-bg)", color: "var(--red)", border: "1px solid var(--red-dim)" }}
          >
            Kill
          </button>
          <button
            onClick={handleClear}
            className="px-2 py-1 text-[10px] rounded transition-colors duration-200"
            style={{ background: "var(--bg-panel)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
          >
            Clear
          </button>
        </div>
      </div>

      {errorText && (
        <div
          className="px-4 py-2 text-[11px] leading-relaxed"
          style={{ background: "var(--red-bg)", color: "var(--red)", borderBottom: "1px solid var(--red-dim)" }}
          title={errorText}
        >
          {errorText}
        </div>
      )}

      <StreamView content={content} className="flex-1 bg-[var(--bg-base)]" />
    </div>
  );
}
