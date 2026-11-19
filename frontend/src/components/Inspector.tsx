"use client";

import Editor from "@monaco-editor/react";
import { useState } from "react";
import type { Feature, FileChange, Flow, ProviderAccount, Skill, Turn } from "../types";
import { FileChanges } from "./FileChanges";
import { ModelSelect } from "./ModelSelect";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

interface Props {
  flow: Flow;
  nodeId: string | null;
  edgeId: string | null;
  feature: Feature | null;
  skills: Skill[];
  providers: ProviderAccount[];
  locked: boolean;
  turns: Turn[];
  files: FileChange[];
  onSaveNode: (nodeId: string, patch: Record<string, unknown>) => Promise<void>;
  onDeleteNode: (nodeId: string) => Promise<void>;
  onSetEnabled: (nodeId: string, enabled: boolean) => Promise<void>;
  onEdgeCondition: (edgeId: string, condition: string) => Promise<void>;
  onDeleteEdge: (edgeId: string) => Promise<void>;
  onNodeSkills: (nodeId: string, skillIds: string[]) => Promise<void>;
  onSaveSkill: (skillId: string, path: string, content: string, skillIds: string[]) => Promise<void>;
  onApprove: (note: string) => Promise<void>;
  onReset: (agentId: string) => Promise<void>;
  onLoadTurns: (agentId: string) => void;
  onClose: () => void;
}

const TABS = ["Config", "Skills", "Context"] as const;

export function Inspector(props: Props) {
  const node = props.flow.nodes.find((item) => item.id === props.nodeId) ?? null;
  const edge = props.flow.edges.find((item) => item.id === props.edgeId) ?? null;
  const [tab, setTab] = useState<(typeof TABS)[number]>("Config");
  const [note, setNote] = useState("Approved. Start implementation.");
  const [message, setMessage] = useState("");
  const [prompt, setPrompt] = useState(node?.system_prompt ?? "");
  const [behavior, setBehavior] = useState(JSON.stringify(node?.behavior_data ?? {}, null, 2));
  const [model, setModel] = useState(node?.model ?? "");
  const [provider, setProvider] = useState(node?.provider || "cursor");
  const [mode, setMode] = useState(node?.cursor_mode ?? "agent");
  const [promptOpen, setPromptOpen] = useState(false);
  const [behaviorOpen, setBehaviorOpen] = useState(false);
  const [skillFile, setSkillFile] = useState("SKILL.md");
  const [skillDraft, setSkillDraft] = useState("");
  const [activeSkill, setActiveSkill] = useState(props.skills[0]?.id ?? "founder-skill");
  const identity = `${node?.id ?? ""}:${edge?.id ?? ""}`;
  const [seen, setSeen] = useState(identity);
  if (seen !== identity) {
    setSeen(identity);
    setPrompt(node?.system_prompt ?? "");
    setBehavior(JSON.stringify(node?.behavior_data ?? {}, null, 2));
    setModel(node?.model ?? "");
    setProvider(node?.provider || "cursor");
    setMode(node?.cursor_mode ?? "agent");
    setMessage("");
  }

  const skill = props.skills.find((item) => item.id === activeSkill) ?? props.skills[0];
  const file = skill?.files.find((item) => item.path === skillFile) ?? skill?.files[0];
  const fileKey = `${skill?.id}:${file?.path}`;
  const [seenFile, setSeenFile] = useState(fileKey);
  if (file && seenFile !== fileKey) {
    setSeenFile(fileKey);
    setSkillDraft(file.content);
    setSkillFile(file.path);
  }

  async function saveConfig() {
    if (!node) return;
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(behavior) as Record<string, unknown>;
    } catch {
      setMessage("Behavior data must be JSON.");
      return;
    }
    await props.onSaveNode(node.id, {
      system_prompt: prompt,
      behavior_data: parsed,
      model,
      provider,
      cursor_mode: mode,
    });
    setMessage("Node saved.");
  }

  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-panel">
      <div className="flex items-start justify-between gap-2 border-b border-line px-3 py-2">
        <div className="min-w-0">
          <div className="text-[10px] font-medium uppercase tracking-wider text-muted">Node inspector</div>
          <h2 className="truncate text-sm">{node?.display_name || edge?.id || "Select a node"}</h2>
          {node?.enabled === false && <p className="text-[11px] text-muted">This agent is off. A run skips it.</p>}
        </div>
        <Button variant="outline" size="sm" onClick={props.onClose} type="button">
          Minimize
        </Button>
      </div>
      {edge && !node && (
        <div className="space-y-3 p-3 text-sm">
          <p className="font-mono text-[11px] text-muted">
            {edge.source} → {edge.target}
          </p>
          <div className="space-y-1.5">
            <Label>Condition</Label>
            <Select disabled={props.locked} value={edge.condition} onValueChange={(value) => void props.onEdgeCondition(edge.id, value)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="always">always</SelectItem>
                <SelectItem value="on_pass">on_pass</SelectItem>
                <SelectItem value="on_fail">on_fail</SelectItem>
                <SelectItem value="on_scale_issue">on_scale_issue</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button variant="destructive" size="sm" disabled={props.locked} onClick={() => void props.onDeleteEdge(edge.id)} type="button">
            Delete edge
          </Button>
        </div>
      )}
      {node && (
        <>
          <Tabs
            value={tab}
            onValueChange={(value) => {
              const next = value as (typeof TABS)[number];
              setTab(next);
              if (next === "Context") props.onLoadTurns(node.id);
            }}
          >
            <TabsList className="m-2">
              {TABS.map((item) => (
                <TabsTrigger key={item} value={item}>
                  {item}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          {tab === "Config" && (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="grid grid-cols-2 gap-2 p-3">
                <div className="space-y-1">
                  <Label>Mode</Label>
                  <Select value={mode} onValueChange={setMode}>
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="plan">plan</SelectItem>
                      <SelectItem value="ask">ask</SelectItem>
                      <SelectItem value="agent">agent</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>Provider</Label>
                  <Select
                    value={provider}
                    onValueChange={(value) => {
                      setProvider(value);
                      setModel("");
                    }}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(props.providers.length ? props.providers : [{ id: "cursor", name: "Cursor" }]).map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="col-span-2 space-y-1">
                  <Label>Model</Label>
                  <div className="mt-1">
                    <ModelSelect
                      models={props.providers.find((item) => item.id === provider)?.models ?? []}
                      value={model}
                      onChange={setModel}
                    />
                  </div>
                </div>
              </div>
              <button
                className="flex items-center justify-between border-y border-line px-3 py-2 text-left text-[11px] text-muted"
                onClick={() => setPromptOpen((open) => !open)}
                type="button"
              >
                <span>System prompt · saved on this node</span>
                <span>{promptOpen ? "Hide" : "Edit"}</span>
              </button>
              {!promptOpen && <p className="truncate px-3 py-2 font-mono text-[10px] text-muted">{prompt.trim() || "Empty"}</p>}
              {promptOpen && (
                <div className="h-48 border-b border-line">
                  <Editor
                    height="100%"
                    theme="vs-dark"
                    language="markdown"
                    value={prompt}
                    onChange={(value) => setPrompt(value ?? "")}
                    options={{ fontSize: 12, minimap: { enabled: false }, wordWrap: "on", fontFamily: "IBM Plex Mono" }}
                  />
                </div>
              )}
              <button
                className="flex items-center justify-between border-b border-line px-3 py-2 text-left text-[11px] text-muted"
                onClick={() => setBehaviorOpen((open) => !open)}
                type="button"
              >
                <span>Behavior data · saved on this node</span>
                <span>{behaviorOpen ? "Hide" : "Edit"}</span>
              </button>
              {!behaviorOpen && <p className="truncate px-3 py-2 font-mono text-[10px] text-muted">{behavior.trim() || "{}"}</p>}
              {behaviorOpen && (
                <div className="h-40">
                  <Editor
                    height="100%"
                    theme="vs-dark"
                    language="json"
                    value={behavior}
                    onChange={(value) => setBehavior(value ?? "{}")}
                    options={{ fontSize: 12, minimap: { enabled: false }, fontFamily: "IBM Plex Mono" }}
                  />
                </div>
              )}
              <div className="mt-auto flex items-center gap-2 border-t border-line p-3">
                <Button size="sm" onClick={() => void saveConfig()} type="button">
                  Save node
                </Button>
                <Button variant="outline" size="sm" onClick={() => void props.onSetEnabled(node.id, node.enabled === false)} type="button">
                  {node.enabled === false ? "Enable agent" : "Disable agent"}
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={props.locked || props.flow.nodes.length < 2}
                  onClick={() => void props.onDeleteNode(node.id)}
                  type="button"
                >
                  Delete agent
                </Button>
                <span className="text-[11px] text-muted">{message}</span>
              </div>
            </div>
          )}
          {tab === "Skills" && skill && file && (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="max-h-40 space-y-1 overflow-auto p-3">
                {props.skills.map((item) => {
                  const checked = node.enabled_skills.includes(item.id);
                  return (
                    <Label key={item.id} className="flex items-center justify-between gap-2 text-xs text-foreground">
                      <span>{item.name}</span>
                      <Checkbox
                        checked={checked}
                        onCheckedChange={() => {
                          const next = checked ? node.enabled_skills.filter((id) => id !== item.id) : [...node.enabled_skills, item.id];
                          void props.onNodeSkills(node.id, next);
                        }}
                      />
                    </Label>
                  );
                })}
              </div>
              <div className="flex items-center gap-2 border-y border-line px-3 py-1">
                <Select value={skill.id} onValueChange={setActiveSkill}>
                  <SelectTrigger className="h-8 w-auto font-mono text-[11px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {props.skills.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={file.path} onValueChange={setSkillFile}>
                  <SelectTrigger className="h-8 w-auto font-mono text-[11px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {skill.files.map((item) => (
                      <SelectItem key={item.path} value={item.path}>
                        {item.path}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="min-h-0 flex-1">
                <Editor
                  height="100%"
                  theme="vs-dark"
                  language={file.path.endsWith(".py") ? "python" : "markdown"}
                  value={skillDraft}
                  onChange={(value) => setSkillDraft(value ?? "")}
                  options={{ fontSize: 12, minimap: { enabled: false }, wordWrap: "on", fontFamily: "IBM Plex Mono" }}
                />
              </div>
              <div className="flex items-center gap-2 border-t border-line p-3">
                <Button variant="outline" size="sm" onClick={() => void props.onSaveSkill(skill.id, file.path, skillDraft, node.enabled_skills)} type="button">
                  Save skill file
                </Button>
                {props.feature?.status === "paused" && (
                  <>
                    <Input className="h-8 min-w-0 flex-1 text-[11px]" value={note} onChange={(event) => setNote(event.target.value)} />
                    <Button size="sm" onClick={() => void props.onApprove(note)} type="button">
                      Approve & Resume
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}
          {tab === "Context" && (
            <ContextTab feature={props.feature} nodeId={node.id} turns={props.turns} files={props.files} onReset={props.onReset} />
          )}
        </>
      )}
    </aside>
  );
}

function ContextTab({
  feature,
  nodeId,
  turns,
  files,
  onReset,
}: {
  feature: Feature | null;
  nodeId: string;
  turns: Turn[];
  files: FileChange[];
  onReset: (agentId: string) => Promise<void>;
}) {
  const sessions = (feature?.sessions ?? []).filter((session) => session.agent_id === nodeId);
  const active = sessions.find((session) => session.status === "active");
  return (
    <div className="min-h-0 flex-1 overflow-auto p-3">
      <div className="rounded border border-line bg-panel2 p-2">
        <div className="text-[10px] uppercase text-muted">Active chat</div>
        <div className="break-all font-mono text-[11px]">{active?.chat_id || "No active chat. The next turn creates one."}</div>
      </div>
      <div className="mt-2">
        <FileChanges files={files.length ? files : active?.files || []} />
      </div>
      <Button className="mt-2 border-amber/50 text-amber" variant="outline" size="sm" disabled={!active || feature?.status === "running"} onClick={() => void onReset(nodeId)} type="button">
        Reset this agent context
      </Button>
      <p className="mt-2 text-[11px] leading-snug text-muted">
        Reset archives this chat id. Retries and QA loops keep using it until you reset or mark the feature done.
      </p>
      <div className="mt-3 space-y-2">
        {turns
          .filter((turn) => turn.agent_id === nodeId)
          .slice(-8)
          .map((turn) => (
            <article key={turn.id} className="rounded border border-line p-2">
              <div className="font-mono text-[10px] text-muted">
                {turn.role} · {turn.chat_id.slice(0, 12)}
              </div>
              <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-paper/90">
                {turn.content}
              </pre>
            </article>
          ))}
      </div>
    </div>
  );
}
