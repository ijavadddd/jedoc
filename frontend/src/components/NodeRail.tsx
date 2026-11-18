"use client";

import { useMemo, useState } from "react";
import type { Flow, Telemetry } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { ScrollArea } from "./ui/scroll-area";

interface Props {
  flow: Flow;
  telemetry: Record<string, Telemetry>;
  selectedId: string | null;
  onSelect: (nodeId: string) => void;
  onClose: () => void;
  onNodeMenu: (nodeId: string, x: number, y: number) => void;
}

export function NodeRail({ flow, telemetry, selectedId, onSelect, onClose, onNodeMenu }: Props) {
  const [query, setQuery] = useState("");
  const nodes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return flow.nodes.filter((node) => {
      if (!needle) return true;
      return `${node.display_name} ${node.id} ${node.role_type} ${node.model}`.toLowerCase().includes(needle);
    });
  }, [flow.nodes, query]);

  return (
    <aside className="flex h-full min-h-0 flex-col bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Saved nodes</div>
          <div className="text-xs">{flow.nodes.length} in this pipeline</div>
        </div>
        <Button variant="outline" size="sm" onClick={onClose} type="button">
          Hide
        </Button>
      </div>
      <div className="border-b border-border p-2">
        <Input className="h-8 text-xs" placeholder="Find a saved node" value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {nodes.length === 0 && <p className="px-3 py-4 text-xs text-muted-foreground">No saved node matches that search.</p>}
        {nodes.map((node) => {
          const off = node.enabled === false;
          const status = off ? "OFF" : telemetry[node.id]?.status || "IDLE";
          const active = node.id === selectedId;
          return (
            <button
              key={node.id}
              className={`block w-full border-b border-border px-3 py-2 text-left ${active ? "bg-accent" : "hover:bg-accent/60"} ${off ? "opacity-60" : ""}`}
              onClick={() => onSelect(node.id)}
              onContextMenu={(event) => {
                event.preventDefault();
                onNodeMenu(node.id, event.clientX, event.clientY);
              }}
              type="button"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm">{node.display_name}</span>
                <Badge variant="outline">{status}</Badge>
              </div>
              <div className="mt-1 truncate font-mono text-[10px] text-sky">
                {node.provider || "cursor"} · {node.model || "account default"}
              </div>
              <div className="font-mono text-[10px] uppercase text-muted-foreground">
                {node.role_type} · {node.cursor_mode}
              </div>
            </button>
          );
        })}
      </ScrollArea>
    </aside>
  );
}
