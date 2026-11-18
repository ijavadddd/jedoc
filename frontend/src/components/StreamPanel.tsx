import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useEffect, useRef } from "react";
import "@xterm/xterm/css/xterm.css";
import type { JedocEvent } from "../types";

function lineFor(event: JedocEvent): string | null {
  if (event.type === "stream") {
    const kind = event.kind || "log";
    const text = (event.text || event.detail || "").replace(/\s+/g, " ").trim();
    if (!text) return null;
    return `[${kind}] ${text}`;
  }
  if (event.type === "qa_progress") return `[qa] ${event.action || ""}`;
  if (event.type === "node_status") return `[${event.node_id}] ${event.status} ${event.action || ""}`.trim();
  if (event.type === "feature_status") return `[feature] ${event.status || ""} ${event.error || ""}`.trim();
  if (event.type === "audit_card") return `[audit ${event.severity}] ${event.table} ${event.check}: ${event.detail || ""}`;
  return null;
}

export function StreamPanel({ events, epoch }: { events: JedocEvent[]; epoch: number }) {
  const host = useRef<HTMLDivElement | null>(null);
  const term = useRef<Terminal | null>(null);
  const written = useRef(0);
  const seenEpoch = useRef(epoch);

  useEffect(() => {
    if (!host.current) return;
    const terminal = new Terminal({
      convertEol: true,
      fontFamily: "IBM Plex Mono, ui-monospace, monospace",
      fontSize: 12,
      theme: {
        background: "#07080b",
        foreground: "#e7ecf3",
        cursor: "#d6a15a",
      },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(host.current);
    fit.fit();
    term.current = terminal;
    written.current = 0;
    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      terminal.dispose();
      term.current = null;
    };
  }, []);

  useEffect(() => {
    const terminal = term.current;
    if (!terminal) return;
    if (seenEpoch.current !== epoch) {
      terminal.reset();
      written.current = 0;
      seenEpoch.current = epoch;
    }
    for (let index = written.current; index < events.length; index += 1) {
      const line = lineFor(events[index]);
      if (line) terminal.writeln(line.slice(0, 500));
    }
    written.current = events.length;
  }, [epoch, events]);

  return (
    <div className="flex h-full min-w-0 flex-col border-r border-line">
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">Cursor CLI stream</span>
        <span className="font-mono text-[10px] text-muted">{events.length} events</span>
      </div>
      <div ref={host} className="min-h-0 flex-1 bg-ink" />
    </div>
  );
}
