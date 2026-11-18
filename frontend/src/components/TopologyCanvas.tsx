import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  applyNodeChanges,
  type Connection,
  type Edge,
  type NodeChange,
  type OnSelectionChangeParams,
  type ReactFlowInstance,
} from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
import "@xyflow/react/dist/style.css";
import { AgentNode, type AgentFlowNode } from "./AgentNode";
import type { Flow, Telemetry } from "../types";

const nodeTypes = { agent: AgentNode };

const EDGE_COLOR: Record<string, string> = {
  always: "#8b95a8",
  on_pass: "#7fd99a",
  on_fail: "#f07178",
  on_scale_issue: "#e6b450",
};

function toFlowNode(flowNode: Flow["nodes"][number], telemetry?: Telemetry): AgentFlowNode {
  return {
    id: flowNode.id,
    type: "agent",
    position: flowNode.position || { x: 0, y: 0 },
    data: {
      label: flowNode.display_name,
      roleType: flowNode.role_type,
      cursorMode: flowNode.cursor_mode,
      model: flowNode.model,
      provider: flowNode.provider || "cursor",
      skills: flowNode.enabled_skills || [],
      status: telemetry?.status || "IDLE",
      chatId: telemetry?.chatId || "",
      files: telemetry?.files || [],
      action: telemetry?.action || "",
      startedAt: telemetry?.startedAt,
      approval: Boolean(flowNode.require_approval_before),
      enabled: flowNode.enabled !== false,
    },
  };
}

function toEdge(edge: Flow["edges"][number]): Edge {
  const color = EDGE_COLOR[edge.condition] || EDGE_COLOR.always;
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_handle,
    targetHandle: edge.target_handle,
    label: edge.condition.replace("on_", "").toUpperCase(),
    data: { condition: edge.condition },
    style: { stroke: color, strokeWidth: 1.4 },
    labelStyle: { fill: color, fontSize: 10 },
    animated: edge.condition === "on_fail" || edge.condition === "on_scale_issue",
  };
}

interface Props {
  flow: Flow;
  telemetry: Record<string, Telemetry>;
  locked: boolean;
  focusNodeId: string | null;
  layoutKey: number;
  onSelectNode: (nodeId: string | null) => void;
  onSelectEdge: (edgeId: string | null) => void;
  onConnect: (connection: Connection) => void;
  onMove: (nodeId: string, position: { x: number; y: number }) => void;
  onNodeMenu: (nodeId: string, x: number, y: number) => void;
}

export function TopologyCanvas({ flow, telemetry, locked, focusNodeId, layoutKey, onSelectNode, onSelectEdge, onConnect, onMove, onNodeMenu }: Props) {
  const [nodes, setNodes] = useState<AgentFlowNode[]>(() => flow.nodes.map((node) => toFlowNode(node, telemetry[node.id])));
  const dragging = useRef(new Set<string>());
  const placed = useRef<Record<string, { x: number; y: number }>>({});
  const instance = useRef<ReactFlowInstance<AgentFlowNode, Edge> | null>(null);
  const edges = useMemo(() => flow.edges.map(toEdge), [flow]);

  useEffect(() => {
    setNodes((current) => {
      const previous = new Map(current.map((node) => [node.id, node]));
      return flow.nodes.map((item) => {
        const built = toFlowNode(item, telemetry[item.id]);
        const live = previous.get(item.id);
        const override = placed.current[item.id];
        if (dragging.current.has(item.id) && live) {
          built.position = live.position;
          built.dragging = true;
        } else if (override && (override.x !== item.position?.x || override.y !== item.position?.y)) {
          built.position = override;
        } else if (override) {
          delete placed.current[item.id];
        }
        if (live?.selected) built.selected = true;
        return built;
      });
    });
  }, [flow, telemetry]);

  useEffect(() => {
    const timer = window.setTimeout(() => void instance.current?.fitView({ padding: 0.2, duration: 180 }), 80);
    return () => window.clearTimeout(timer);
  }, [flow.id, layoutKey, flow.nodes.length]);

  useEffect(() => {
    if (!focusNodeId) return;
    const node = flow.nodes.find((item) => item.id === focusNodeId);
    if (!node) return;
    const timer = window.setTimeout(() => {
      void instance.current?.setCenter(node.position.x + 120, node.position.y + 48, { zoom: 1, duration: 200 });
    }, 30);
    return () => window.clearTimeout(timer);
  }, [focusNodeId, flow.nodes]);

  function onSelection(params: OnSelectionChangeParams) {
    const node = params.nodes[0];
    const edge = params.edges[0];
    if (node) {
      onSelectNode(node.id);
      onSelectEdge(null);
    } else if (edge) {
      onSelectNode(null);
      onSelectEdge(edge.id);
    }
  }

  return (
    <div className="relative h-full min-h-0 w-full min-w-0 flex-1 bg-ink">
      <ReactFlow
        className="h-full w-full"
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={(graph) => {
          instance.current = graph;
          void graph.fitView({ padding: 0.2 });
        }}
        onNodesChange={(changes: NodeChange<AgentFlowNode>[]) => {
          for (const change of changes) {
            if (change.type === "position" && change.id) {
              if (change.dragging) dragging.current.add(change.id);
              if (change.dragging === false) dragging.current.delete(change.id);
            }
          }
          setNodes((current) => applyNodeChanges(changes, current));
        }}
        onSelectionChange={onSelection}
        onNodeClick={(_, node) => {
          onSelectNode(node.id);
        }}
        onNodeContextMenu={(event, node) => {
          event.preventDefault();
          onNodeMenu(node.id, event.clientX, event.clientY);
        }}
        onPaneContextMenu={(event) => event.preventDefault()}
        onEdgeClick={(_, edge) => {
          onSelectEdge(edge.id);
        }}
        onPaneClick={() => {
          onSelectNode(null);
          onSelectEdge(null);
        }}
        onConnect={locked ? undefined : onConnect}
        onNodeDragStop={(_, node) => {
          placed.current[node.id] = node.position;
          onMove(node.id, node.position);
        }}
        nodesDraggable
        nodesConnectable={!locked}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: "smoothstep" }}
      >
        <Background color="#262b36" gap={22} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) => {
            const status = (node.data as AgentFlowNode["data"] | undefined)?.status;
            if (status === "RUNNING") return "#7cb7ff";
            if (status === "WAITING_APPROVAL") return "#e6b450";
            if (status === "PASSED") return "#7fd99a";
            if (status === "FAILED" || status === "FAILED_RETRYING") return "#f07178";
            return "#2a3140";
          }}
          maskColor="rgb(7 8 11 / 72%)"
        />
      </ReactFlow>
      <div className="pointer-events-none absolute left-3 top-3 flex gap-2 font-mono text-[10px] text-muted">
        <span className="rounded border border-line bg-panel/90 px-2 py-1">drag nodes to rearrange</span>
        <span className="rounded border border-line bg-panel/90 px-2 py-1">right-click to enable, disable, or delete</span>
        <span className="rounded border border-line bg-panel/90 px-2 py-1">out = forward</span>
        <span className="rounded border border-line bg-panel/90 px-2 py-1 text-coral">fail handle loops back</span>
        <span className="rounded border border-line bg-panel/90 px-2 py-1 text-amber">scale returns to the architect</span>
      </div>
    </div>
  );
}
