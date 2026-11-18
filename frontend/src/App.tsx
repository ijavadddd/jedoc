"use client";

import { useEffect, useMemo, useState } from "react";
import type { Connection } from "@xyflow/react";
import { api } from "./api";
import { AgentDialog } from "./components/AgentDialog";
import { FeatureDialog } from "./components/FeatureDialog";
import { GuideToy } from "./components/GuideToy";
import { Inspector } from "./components/Inspector";
import { Landing } from "./components/Landing";
import { NodeContextMenu } from "./components/NodeContextMenu";
import { NodeRail } from "./components/NodeRail";
import { ProjectChat } from "./components/ProjectChat";
import { ProvidersView } from "./components/ProvidersView";
import { Button } from "./components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import { QaPanel } from "./components/QaPanel";
import { ResizeBar } from "./components/ResizeBar";
import { SkillsView } from "./components/SkillsView";
import { StreamPanel } from "./components/StreamPanel";
import { TargetBar } from "./components/TargetBar";
import { TopologyCanvas } from "./components/TopologyCanvas";
import type { AgentInfo, AuditCard, Feature, Flow, GitProject, GitRepo, JedocEvent, ProviderAccount, QaProgress, Session, Skill, Telemetry, Turn } from "./types";

const EMPTY_FLOW: Flow = {
  id: "",
  name: "Jedoc",
  entry: "",
  interrupt_before: [],
  nodes: [],
  edges: [],
};

export function App() {
  const [view, setView] = useState<"pipeline" | "skills" | "providers">("pipeline");
  const [flow, setFlow] = useState<Flow>(EMPTY_FLOW);
  const [features, setFeatures] = useState<Feature[]>([]);
  const [feature, setFeature] = useState<Feature | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [events, setEvents] = useState<JedocEvent[]>([]);
  const [epoch, setEpoch] = useState(0);
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [nodeMenu, setNodeMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const [edgeId, setEdgeId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [dialog, setDialog] = useState(false);
  const [agentDialog, setAgentDialog] = useState(false);
  const [banner, setBanner] = useState("");
  const [projects, setProjects] = useState<GitProject[]>([]);
  const [projectsRoot, setProjectsRoot] = useState("");
  const [repo, setRepo] = useState<GitRepo | null>(null);
  const [projectPath, setProjectPath] = useState("");
  const [branch, setBranch] = useState("");
  const [useWorktree, setUseWorktree] = useState(false);
  const [providers, setProviders] = useState<ProviderAccount[]>([]);
  const [screen, setScreen] = useState<"landing" | "guide" | "app">(() =>
    window.localStorage.getItem("jedoc.entered") === "1" ? "app" : "landing",
  );
  const [railOpen, setRailOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [dockOpen, setDockOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [chatWidth, setChatWidth] = useState(380);
  const [railWidth, setRailWidth] = useState(240);
  const [inspectorWidth, setInspectorWidth] = useState(360);
  const [dockHeight, setDockHeight] = useState(220);
  const [layoutKey, setLayoutKey] = useState(1);
  const [browsing, setBrowsing] = useState(false);

  function enterApp() {
    window.localStorage.setItem("jedoc.entered", "1");
    setScreen("app");
    setLayoutKey((value) => value + 1);
  }

  function selectNode(id: string | null) {
    setNodeId(id);
    setEdgeId(null);
    setInspectorOpen(Boolean(id));
    setNodeMenu(null);
  }

  function openNodeMenu(id: string, x: number, y: number) {
    setNodeId(id);
    setEdgeId(null);
    setNodeMenu({ id, x, y });
  }

  function setNodeEnabled(id: string, enabled: boolean) {
    setNodeMenu(null);
    return guard(async () => {
      if (!flow.id) return;
      setFlow(await api<Flow>(`/api/flows/${flow.id}/nodes/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }));
    });
  }

  function removeNode(id: string) {
    setNodeMenu(null);
    return guard(async () => {
      if (!flow.id || locked) return;
      setFlow(await api<Flow>(`/api/flows/${flow.id}/nodes/${id}`, { method: "DELETE" }));
      if (nodeId === id) {
        setNodeId(null);
        setInspectorOpen(false);
      }
    });
  }

  async function loadSkills(workspace?: string) {
    const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
    setSkills(await api<Skill[]>(`/api/skills${query}`));
  }

  async function selectFeature(id: string) {
    const detail = await api<Feature>(`/api/features/${id}`);
    setFeature(detail);
    setFlow(await api<Flow>(`/api/flows/${detail.flow_id}`));
    await loadSkills(detail.workspace_path);
  }

  useEffect(() => {
    void (async () => {
      try {
        const [flowList, featureList, skillList, agentInfo, projectPayload, providerList] = await Promise.all([
          api<Flow[]>("/api/flows"),
          api<Feature[]>("/api/features"),
          api<Skill[]>("/api/skills"),
          api<AgentInfo>("/api/agent/status"),
          api<{ root: string; projects: GitProject[] }>("/api/git/projects"),
          api<ProviderAccount[]>("/api/providers"),
        ]);
        const initial = flowList.find((item) => item.id === "jedoc-million-user") ?? flowList[0];
        if (initial) setFlow(initial);
        setFeatures(featureList);
        setSkills(skillList);
        setAgent(agentInfo);
        setProjects(projectPayload.projects);
        setProjectsRoot(projectPayload.root);
        setProviders(providerList);
        if (featureList[0]) await selectFeature(featureList[0].id);
      } catch (err) {
        setBanner(err instanceof Error ? err.message : "Could not reach the Jedoc API");
      }
    })();
  }, []);

  useEffect(() => {
    if (!feature) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${proto}//${location.host}/ws/features/${feature.id}`);
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as JedocEvent;
      if (event.type === "hello") {
        setEvents(event.events ?? []);
        setEpoch((value) => value + 1);
        if (event.feature) {
          setFeature((current) =>
            current
              ? { ...current, ...event.feature, sessions: event.sessions ?? current.sessions, artifacts: event.artifacts ?? current.artifacts }
              : current,
          );
        }
        return;
      }
      setEvents((current) => [...current.slice(-700), event]);
      if (event.type === "feature_status") {
        setFeature((current) => (current ? { ...current, status: event.status || current.status, error: event.error || "" } : current));
        void api<Feature>(`/api/features/${feature.id}`).then(setFeature).catch(() => undefined);
        void api<Feature[]>("/api/features").then(setFeatures).catch(() => undefined);
      }
    };
    return () => socket.close();
  }, [feature?.id]);

  useEffect(() => {
    if (!feature?.project_path) return;
    setProjectPath(feature.project_path);
    setBranch(feature.branch || "");
    setUseWorktree(Boolean(feature.use_worktree));
  }, [feature?.id, feature?.project_path, feature?.branch, feature?.use_worktree]);

  useEffect(() => {
    if (!projectPath) {
      setRepo(null);
      return;
    }
    let cancelled = false;
    api<GitRepo>(`/api/git/repo?path=${encodeURIComponent(projectPath)}`)
      .then((next) => {
        if (cancelled) return;
        setRepo(next);
        setBranch((current) => (current && next.branches.includes(current) ? current : next.branch));
      })
      .catch((err: unknown) => {
        if (!cancelled) setBanner(err instanceof Error ? err.message : "Could not read the repository");
      });
    return () => {
      cancelled = true;
    };
  }, [projectPath]);

  useEffect(() => {
    setLayoutKey((value) => value + 1);
  }, [railOpen, inspectorOpen, dockOpen, screen, chatOpen]);

  const derived = useMemo(() => reduceEvents(events, feature?.sessions ?? []), [events, feature?.sessions]);
  const locked = feature?.status === "running" || feature?.status === "paused";

  async function guard(action: () => Promise<void>) {
    try {
      setBanner("");
      await action();
    } catch (err) {
      setBanner(err instanceof Error ? err.message : "Request failed");
    }
  }

  async function reloadFlow(next?: Flow) {
    if (next) {
      setFlow(next);
      return;
    }
    if (flow.id) setFlow(await api<Flow>(`/api/flows/${flow.id}`));
  }

  if (screen === "landing") {
    return <Landing onEnter={enterApp} onGuide={() => setScreen("guide")} />;
  }
  if (screen === "guide") {
    return <GuideToy onDone={enterApp} onBack={() => setScreen("landing")} />;
  }

  return (
    <div className="flex h-screen flex-col bg-ink text-paper">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-3">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded bg-gold font-mono text-xs font-medium text-ink">Jd</span>
          <div>
            <div className="text-sm font-medium leading-none">Jedoc</div>
            <div className="mt-1 font-mono text-[10px] text-muted">{flow.name || "pipeline"}</div>
          </div>
        </div>
        <Tabs value={view} onValueChange={(value) => setView(value as "pipeline" | "skills" | "providers")}>
          <TabsList>
            <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
            <TabsTrigger value="skills">Skills</TabsTrigger>
            <TabsTrigger value="providers">Providers</TabsTrigger>
          </TabsList>
        </Tabs>
        <Button variant="outline" size="sm" onClick={() => setScreen("landing")} type="button">
          Home
        </Button>
        <Button variant="outline" size="sm" onClick={() => setScreen("guide")} type="button">
          Guide
        </Button>
        {!chatOpen && (
          <Button variant="outline" size="sm" onClick={() => setChatOpen(true)} type="button">
            Show chat
          </Button>
        )}
        <Select
          value={feature?.id || "none"}
          onValueChange={(value) => {
            if (value !== "none") void selectFeature(value);
          }}
        >
          <SelectTrigger className="h-8 w-[220px] text-xs">
            <SelectValue placeholder="No feature" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">No feature</SelectItem>
            {features.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.name} · {item.status}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <StatusPill label={feature?.status ?? "idle"} />
        <StatusPill label={agent ? `${agent.execution_mode}${agent.authenticated ? " · cli" : ""}` : "cli"} />
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={!flow.id || locked} onClick={() => setAgentDialog(true)} type="button">
            Add agent
          </Button>
          <Button variant="outline" size="sm" onClick={() => setDialog(true)} type="button">
            New feature
          </Button>
          {feature && (feature.status === "draft" || feature.status === "failed") && (
            <Button
              size="sm"
              onClick={() =>
                void guard(async () => {
                  await api(`/api/features/${feature.id}/start`, { method: "POST" });
                  await selectFeature(feature.id);
                  setFeatures(await api<Feature[]>("/api/features"));
                })
              }
              type="button"
            >
              Start pipeline
            </Button>
          )}
          {feature?.status === "paused" && (
            <Button
              size="sm"
              onClick={() =>
                void guard(async () => {
                  await api(`/api/features/${feature.id}/approve`, {
                    method: "POST",
                    body: JSON.stringify({ note: "Approved from the header." }),
                  });
                  await selectFeature(feature.id);
                  setFeatures(await api<Feature[]>("/api/features"));
                })
              }
              type="button"
            >
              Approve & Resume
            </Button>
          )}
          {feature && feature.status !== "archived" && (
            <Button
              className="border-amber/50 text-amber"
              variant="outline"
              size="sm"
              onClick={() => void guard(() => api(`/api/features/${feature.id}/mark-done`, { method: "POST" }).then(() => selectFeature(feature.id)))}
              type="button"
            >
              Mark feature done
            </Button>
          )}
        </div>
      </header>
      {banner && <div className="border-b border-coral/40 bg-coral/10 px-3 py-1 text-xs text-coral">{banner}</div>}
      {agent && !agent.installed && (
        <div className="border-b border-amber/40 bg-amber/10 px-3 py-1 text-xs text-amber">
          Cursor CLI is not on PATH. Set JEDOC_EXECUTION_MODE=simulate or install `agent`.
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {view === "providers" ? (
        <div className="min-h-0 flex-1">
          <ProvidersView
            providers={providers}
            onSave={async (input) => {
              await api("/api/providers/cursor", { method: "PUT", body: JSON.stringify(input) });
              setProviders(await api<ProviderAccount[]>("/api/providers"));
            }}
            onRefresh={async () => {
              const refreshed = await api<ProviderAccount>("/api/providers/cursor/refresh", { method: "POST" });
              setProviders((current) => current.map((item) => (item.id === "cursor" ? refreshed : item)));
              setAgent(await api<AgentInfo>("/api/agent/status"));
            }}
            onLogin={async () => api("/api/providers/cursor/login", { method: "POST" })}
            onLogout={async () => {
              await api("/api/providers/cursor/logout", { method: "POST" });
              setProviders(await api<ProviderAccount[]>("/api/providers"));
              setAgent(await api<AgentInfo>("/api/agent/status"));
            }}
          />
        </div>
      ) : view === "skills" ? (
        <div className="min-h-0 flex-1">
          <SkillsView
            skills={skills}
            workspace={feature?.workspace_path}
            onToggle={(skillId, enabled) =>
              guard(async () => {
                const enabledIds = skills.filter((item) => (item.id === skillId ? enabled : item.enabled)).map((item) => item.id);
                await api(`/api/skills/${skillId}/toggle`, {
                  method: "PATCH",
                  body: JSON.stringify({
                    enabled,
                    workspace: feature?.workspace_path,
                    skill_ids: feature ? enabledIds : undefined,
                  }),
                });
                await loadSkills(feature?.workspace_path);
              })
            }
            onSave={(skillId, path, content) =>
              guard(async () => {
                const enabledIds = skills.filter((item) => item.enabled).map((item) => item.id);
                await api(`/api/skills/${skillId}/content`, {
                  method: "PUT",
                  body: JSON.stringify({
                    path,
                    content,
                    workspace: feature?.workspace_path,
                    skill_ids: feature ? enabledIds : undefined,
                  }),
                });
                await loadSkills(feature?.workspace_path);
              })
            }
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <TargetBar
            projects={projects}
            root={projectsRoot}
            projectPath={projectPath}
            branch={branch}
            branches={repo?.branches ?? []}
            dirty={Boolean(repo?.dirty)}
            useWorktree={useWorktree}
            workspace={feature?.workspace_path ?? ""}
            disabled={!feature || locked}
            browsing={browsing}
            onBrowse={() =>
              void guard(async () => {
                setBrowsing(true);
                try {
                  const result = await api<{ path: string | null; repo: GitRepo | null }>("/api/git/pick", { method: "POST" });
                  if (!result.path) return;
                  setProjectPath(result.path);
                  if (!result.repo) setBanner("That folder is not a git repository. Initialize git there, or choose another folder.");
                } finally {
                  setBrowsing(false);
                }
              })
            }
            onProject={setProjectPath}
            onBranch={setBranch}
            onWorktree={setUseWorktree}
            onApply={() =>
              void guard(async () => {
                if (!feature) return;
                const updated = await api<Feature>(`/api/features/${feature.id}/target`, {
                  method: "PATCH",
                  body: JSON.stringify({ project_path: projectPath, branch, use_worktree: useWorktree }),
                });
                setFeature(updated);
                setFeatures(await api<Feature[]>("/api/features"));
                await loadSkills(updated.workspace_path);
              })
            }
          />
          <div className="flex items-center gap-2 border-b border-line px-2 py-1">
            {!railOpen && (
              <Button variant="outline" size="sm" onClick={() => setRailOpen(true)} type="button">
                Show nodes
              </Button>
            )}
            {!inspectorOpen && (
              <Button variant="outline" size="sm" disabled={!nodeId} onClick={() => setInspectorOpen(true)} type="button">
                Show inspector
              </Button>
            )}
            {!dockOpen && (
              <Button variant="outline" size="sm" onClick={() => setDockOpen(true)} type="button">
                Show stream
              </Button>
            )}
          </div>
          <div className="flex min-h-0 flex-1">
            {railOpen && flow.id && (
              <>
                <div className="h-full shrink-0 border-r border-line" style={{ width: railWidth }}>
                  <NodeRail
                    flow={flow}
                    telemetry={derived.telemetry}
                    selectedId={nodeId}
                    onSelect={selectNode}
                    onClose={() => setRailOpen(false)}
                    onNodeMenu={openNodeMenu}
                  />
                </div>
                <ResizeBar axis="x" onDelta={(delta) => setRailWidth((width) => Math.min(420, Math.max(180, width + delta)))} />
              </>
            )}
            {flow.id ? (
              <TopologyCanvas
                flow={flow}
                telemetry={derived.telemetry}
                locked={locked}
                focusNodeId={nodeId}
                layoutKey={layoutKey}
                onSelectNode={selectNode}
                onSelectEdge={(id) => {
                  setEdgeId(id);
                  setNodeId(null);
                  setInspectorOpen(Boolean(id));
                }}
                onConnect={(connection) => void connectEdge(connection)}
                onMove={(id, position) =>
                  void guard(async () => {
                    const saved = await api<Flow>(`/api/flows/${flow.id}/nodes/${id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ position }),
                    });
                    setFlow(saved);
                  })
                }
                onNodeMenu={openNodeMenu}
              />
            ) : (
              <div className="grid flex-1 place-items-center text-sm text-muted">Waiting for the pipeline template.</div>
            )}
            {flow.id && inspectorOpen && (
              <>
                <ResizeBar
                  axis="x"
                  onDelta={(delta) => setInspectorWidth((width) => Math.min(640, Math.max(280, width - delta)))}
                />
                <div className="h-full shrink-0 border-l border-line" style={{ width: inspectorWidth }}>
              <Inspector
                flow={flow}
                nodeId={nodeId}
                edgeId={edgeId}
                feature={feature}
                skills={skills}
                providers={providers}
                locked={Boolean(locked)}
                turns={turns}
                files={derived.telemetry[nodeId || ""]?.files || []}
                onSaveNode={(id, patch) =>
                  guard(async () => {
                    setFlow(await api<Flow>(`/api/flows/${flow.id}/nodes/${id}`, { method: "PATCH", body: JSON.stringify(patch) }));
                  })
                }
                onDeleteNode={(id) => removeNode(id)}
                onSetEnabled={(id, enabled) => setNodeEnabled(id, enabled)}
                onEdgeCondition={(id, condition) =>
                  guard(async () => {
                    const definition = {
                      ...flow,
                      edges: flow.edges.map((edge) => (edge.id === id ? { ...edge, condition } : edge)),
                    };
                    setFlow(await api<Flow>(`/api/flows/${flow.id}`, { method: "PUT", body: JSON.stringify({ definition }) }));
                  })
                }
                onDeleteEdge={(id) =>
                  guard(async () => {
                    setFlow(await api<Flow>(`/api/flows/${flow.id}/edges/${id}`, { method: "DELETE" }));
                    setEdgeId(null);
                  })
                }
                onNodeSkills={(id, skillIds) =>
                  guard(async () => {
                    setFlow(
                      await api<Flow>(`/api/flows/${flow.id}/nodes/${id}`, {
                        method: "PATCH",
                        body: JSON.stringify({ enabled_skills: skillIds }),
                      }),
                    );
                    if (feature) {
                      await api("/api/skills/sync", {
                        method: "POST",
                        body: JSON.stringify({ workspace: feature.workspace_path, skill_ids: skillIds }),
                      });
                      await loadSkills(feature.workspace_path);
                    }
                  })
                }
                onSaveSkill={(skillId, path, content, skillIds) =>
                  guard(async () => {
                    await api(`/api/skills/${skillId}/content`, {
                      method: "PUT",
                      body: JSON.stringify({
                        path,
                        content,
                        workspace: feature?.workspace_path,
                        skill_ids: feature ? skillIds : undefined,
                      }),
                    });
                    await loadSkills(feature?.workspace_path);
                  })
                }
                onApprove={(note) =>
                  guard(async () => {
                    if (!feature) return;
                    await api(`/api/features/${feature.id}/approve`, { method: "POST", body: JSON.stringify({ note }) });
                  })
                }
                onReset={(agentId) =>
                  guard(async () => {
                    if (!feature) return;
                    await api(`/api/features/${feature.id}/sessions/${agentId}/reset`, { method: "POST" });
                    await selectFeature(feature.id);
                  })
                }
                onLoadTurns={(agentId) => {
                  if (!feature) return;
                  void api<{ turns: Turn[] }>(`/api/features/${feature.id}/sessions?agent_id=${agentId}`)
                    .then((payload) => setTurns(payload.turns))
                    .catch((err: unknown) => setBanner(err instanceof Error ? err.message : "Could not load context"));
                }}
                onClose={() => {
                  setInspectorOpen(false);
                  setNodeId(null);
                  setEdgeId(null);
                }}
              />
                </div>
              </>
            )}
          </div>
          {dockOpen ? (
            <>
              <ResizeBar axis="y" onDelta={(delta) => setDockHeight((height) => Math.min(480, Math.max(120, height - delta)))} />
              <div className="flex shrink-0 flex-col border-t border-line" style={{ height: dockHeight }}>
                <div className="flex justify-end border-b border-line px-2 py-1">
                  <Button variant="ghost" size="sm" onClick={() => setDockOpen(false)} type="button">
                    Minimize stream
                  </Button>
                </div>
                <div className="grid min-h-0 flex-1 grid-cols-[1.45fr_0.8fr]">
                  <StreamPanel events={events} epoch={epoch} />
                  <QaPanel progress={derived.progress} cards={derived.cards} />
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}
        </div>
        {chatOpen && (
          <>
            <ResizeBar axis="x" onDelta={(delta) => setChatWidth((width) => Math.min(560, Math.max(300, width - delta)))} />
            <ProjectChat
              workspace={projectPath || feature?.workspace_path || ""}
              providers={providers}
              width={chatWidth}
              onClose={() => setChatOpen(false)}
            />
          </>
        )}
      </div>
      <FeatureDialog
        open={dialog}
        checkout={projectPath && branch ? `${projectPath} @ ${branch}${useWorktree ? " (worktree)" : ""}` : ""}
        onClose={() => setDialog(false)}
        onCreate={async (input) => {
          const payload = {
            ...input,
            ...(projectPath && branch
              ? { project_path: projectPath, branch, use_worktree: useWorktree, workspace_path: undefined }
              : {}),
          };
          const created = await api<Feature>("/api/features", { method: "POST", body: JSON.stringify(payload) });
          setFeatures(await api<Feature[]>("/api/features"));
          await selectFeature(created.id);
        }}
      />
      {nodeMenu && view === "pipeline" && (
        <NodeContextMenu
          x={nodeMenu.x}
          y={nodeMenu.y}
          name={flow.nodes.find((node) => node.id === nodeMenu.id)?.display_name || "Agent"}
          enabled={flow.nodes.find((node) => node.id === nodeMenu.id)?.enabled !== false}
          canDelete={!locked && flow.nodes.length > 1}
          onToggle={() => {
            const node = flow.nodes.find((item) => item.id === nodeMenu.id);
            void setNodeEnabled(nodeMenu.id, node?.enabled === false);
          }}
          onDelete={() => void removeNode(nodeMenu.id)}
          onClose={() => setNodeMenu(null)}
        />
      )}
      <AgentDialog
        open={agentDialog}
        providers={providers}
        onClose={() => setAgentDialog(false)}
        onCreate={async (input) => {
          const saved = await api<Flow>(`/api/flows/${flow.id}/nodes`, { method: "POST", body: JSON.stringify(input) });
          setFlow(saved);
          const created = saved.nodes[saved.nodes.length - 1];
          if (created) selectNode(created.id);
        }}
      />
    </div>
  );

  function connectEdge(connection: Connection) {
    if (!connection.source || !connection.target) return;
    void guard(async () => {
      const saved = await api<Flow>(`/api/flows/${flow.id}/edges`, {
        method: "POST",
        body: JSON.stringify({
          source: connection.source,
          target: connection.target,
          condition: "on_pass",
          source_handle: connection.sourceHandle,
          target_handle: connection.targetHandle,
        }),
      });
      await reloadFlow(saved);
    });
  }
}

function StatusPill({ label }: { label: string }) {
  const tone =
    label === "running"
      ? "text-sky border-sky/40"
      : label === "paused"
        ? "text-amber border-amber/50"
        : label === "completed"
          ? "text-mint border-mint/40"
          : label === "failed"
            ? "text-coral border-coral/50"
            : "text-muted border-line";
  return <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase ${tone}`}>{label}</span>;
}

function reduceEvents(
  events: JedocEvent[],
  sessions: Session[] = [],
): { telemetry: Record<string, Telemetry>; cards: AuditCard[]; progress: QaProgress | null } {
  const telemetry: Record<string, Telemetry> = {};
  for (const session of sessions) {
    if (session.status !== "active") continue;
    telemetry[session.agent_id] = {
      status: "IDLE",
      chatId: session.chat_id,
      action: "",
      files: session.files || [],
    };
  }
  const cards: AuditCard[] = [];
  let progress: QaProgress | null = null;
  for (const event of events) {
    if (event.type === "node_status" && event.node_id) {
      const previous = telemetry[event.node_id];
      telemetry[event.node_id] = {
        status: event.status || previous?.status || "IDLE",
        chatId: event.chat_id || previous?.chatId || "",
        action: event.action || previous?.action || "",
        files: previous?.files || [],
        startedAt: event.started_at || previous?.startedAt,
      };
    } else if (event.type === "file_changes" && event.node_id) {
      const previous = telemetry[event.node_id];
      telemetry[event.node_id] = {
        status: previous?.status || "IDLE",
        chatId: event.chat_id || previous?.chatId || "",
        action: previous?.action || "",
        files: event.files || [],
        startedAt: previous?.startedAt,
      };
    } else if (event.type === "qa_progress") {
      progress = {
        elapsed_s: event.elapsed_s ?? 0,
        duration_s: event.duration_s ?? 600,
        configured_duration_s: event.configured_duration_s,
        action: event.action || "",
      };
    } else if (event.type === "audit_card") {
      cards.push({
        severity: event.severity || "info",
        table: event.table || "—",
        check: event.check || "check",
        detail: event.detail || "",
      });
    }
  }
  return { telemetry, cards, progress };
}
