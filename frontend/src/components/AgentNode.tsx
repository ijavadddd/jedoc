import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { useEffect, useState } from "react";
import type { FileChange } from "../types";
import { FileChanges } from "./FileChanges";

export type AgentNodeData = {
  label: string;
  roleType: string;
  cursorMode: string;
  model: string;
  provider: string;
  skills: string[];
  status: string;
  chatId: string;
  files: FileChange[];
  action: string;
  startedAt?: number;
  approval: boolean;
  enabled: boolean;
};

export type AgentFlowNode = Node<AgentNodeData, "agent">;

const STATUS_CLASS: Record<string, string> = {
  IDLE: "text-muted border-line",
  RUNNING: "text-sky border-sky/60",
  WAITING_APPROVAL: "text-amber border-amber/70",
  PASSED: "text-mint border-mint/50",
  FAILED_RETRYING: "text-coral border-coral/70",
  FAILED: "text-coral border-coral/70",
};

function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

export function AgentNode({ data, selected }: NodeProps<AgentFlowNode>) {
  const [now, setNow] = useState(() => Date.now());
  const live = data.status === "RUNNING" || data.status === "WAITING_APPROVAL";
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [live]);
  const elapsed = data.startedAt ? Math.max(0, now / 1000 - data.startedAt) : 0;
  const off = data.enabled === false;
  const tone = off ? "text-muted border-line" : (STATUS_CLASS[data.status] ?? STATUS_CLASS.IDLE);
  const shownSkills = data.skills.slice(0, 3);
  const extra = data.skills.length - shownSkills.length;

  return (
    <div
      className={`w-[240px] rounded-[12px] border bg-panel shadow-panel ${off ? "border-dashed opacity-60" : ""} ${selected ? "border-gold" : "border-line"}`}
    >
      <Handle id="back" type="target" position={Position.Top} className="!bg-amber !h-2 !w-2" />
      <Handle id="in" type="target" position={Position.Left} className="!bg-muted !h-2 !w-2" />
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium">{data.label}</div>
          <div className="font-mono text-[10px] uppercase tracking-wide text-muted">
            {data.roleType} · {data.cursorMode}
          </div>
          <div className="truncate font-mono text-[10px] text-sky" title={data.model || "account default"}>
            {data.provider || "cursor"} · {data.model || "account default"}
          </div>
        </div>
        <span className={`shrink-0 rounded-full border px-1.5 py-0.5 font-mono text-[9px] ${tone}`}>
          <span className={!off && data.status === "RUNNING" ? "pulse-dot" : ""}>{off ? "OFF" : data.status}</span>
        </span>
      </div>
      <div className="space-y-2 px-3 py-2">
        <div className="flex items-center justify-between font-mono text-[10px] text-muted">
          <span className="truncate">{data.chatId ? data.chatId.slice(0, 18) : "no chat yet"}</span>
          <span>{live ? clock(elapsed) : data.status === "IDLE" ? "idle" : ""}</span>
        </div>
        <p className="line-clamp-2 min-h-[28px] text-[11px] leading-snug text-paper/90">
          {off ? "Disabled. A run skips this agent." : data.action || (data.approval ? "Approval gate on the way in" : "Idle")}
        </p>
        <FileChanges files={data.files || []} />
        <div className="flex flex-wrap gap-1">
          {shownSkills.map((skill) => (
            <span key={skill} className="rounded bg-panel2 px-1.5 py-0.5 font-mono text-[9px] text-gold">
              {skill}
            </span>
          ))}
          {extra > 0 && <span className="font-mono text-[9px] text-muted">+{extra}</span>}
        </div>
      </div>
      <Handle id="out" type="source" position={Position.Right} className="!bg-mint !h-2 !w-2" />
      <Handle id="fail" type="source" position={Position.Bottom} className="!bg-coral !h-2 !w-2" style={{ left: "68%" }} />
      <Handle id="scale" type="source" position={Position.Bottom} className="!bg-amber !h-2 !w-2" style={{ left: "32%" }} />
    </div>
  );
}
