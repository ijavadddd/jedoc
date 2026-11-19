"use client";

import { useEffect, useMemo, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { JedocEvent } from "../types";

type FeedItem =
  | { key: string; kind: "meta"; tone: string; label: string; body: string }
  | { key: string; kind: "markdown"; tone: string; label: string; body: string }
  | { key: string; kind: "code"; tone: string; label: string; body: string };

function toneFor(kind: string): string {
  if (kind === "thinking") return "text-muted";
  if (kind === "assistant") return "text-paper";
  if (kind === "shell") return "text-mint";
  if (kind === "mcp" || kind === "tool_call") return "text-sky";
  if (kind === "system") return "text-amber";
  if (kind === "error" || kind === "failed") return "text-coral";
  return "text-muted";
}

function looksLikeMarkdown(text: string): boolean {
  return /(^#{1,6}\s)|(```)|(\*\*[^*]+\*\*)|(^\s*[-*]\s)|(^\s*\d+\.\s)|(\[[^\]]+\]\([^)]+\))/m.test(text);
}

function buildFeed(events: JedocEvent[]): FeedItem[] {
  const items: FeedItem[] = [];
  let assistant = "";
  let assistantKey = "";

  const flushAssistant = () => {
    if (!assistant.trim()) {
      assistant = "";
      assistantKey = "";
      return;
    }
    items.push({
      key: assistantKey || `assistant-${items.length}`,
      kind: "markdown",
      tone: toneFor("assistant"),
      label: "assistant",
      body: assistant,
    });
    assistant = "";
    assistantKey = "";
  };

  events.forEach((event, index) => {
    if (event.type === "stream") {
      const kind = event.kind || "log";
      const text = (event.text || event.detail || "").trimEnd();
      if (kind === "assistant") {
        if (!assistantKey) assistantKey = `assistant-${event.id || index}`;
        assistant += text;
        return;
      }
      flushAssistant();
      if (kind === "session") {
        if (text) items.push({ key: `s-${index}`, kind: "meta", tone: toneFor(kind), label: "session", body: text });
        return;
      }
      if (kind === "thinking") {
        items.push({
          key: `t-${index}`,
          kind: "meta",
          tone: toneFor(kind),
          label: "thinking",
          body: text || "…",
        });
        return;
      }
      if (kind === "shell") {
        items.push({
          key: `sh-${index}`,
          kind: "code",
          tone: toneFor(kind),
          label: "$",
          body: text || event.name || "shell",
        });
        return;
      }
      if (kind === "tool_call" || kind === "mcp") {
        items.push({
          key: `tool-${index}`,
          kind: "meta",
          tone: toneFor(kind),
          label: kind === "mcp" ? `mcp ${event.name || "tool"}` : event.name || "tool",
          body: text,
        });
        return;
      }
      if (kind === "system") {
        items.push({
          key: `sys-${index}`,
          kind: looksLikeMarkdown(text) ? "markdown" : "meta",
          tone: toneFor(event.level === "error" ? "error" : kind),
          label: event.level === "error" ? "error" : "system",
          body: text,
        });
        return;
      }
      if (text) {
        items.push({
          key: `x-${index}`,
          kind: looksLikeMarkdown(text) ? "markdown" : "meta",
          tone: toneFor(kind),
          label: kind,
          body: text,
        });
      }
      return;
    }

    flushAssistant();
    if (event.type === "qa_progress") {
      items.push({
        key: `qa-${index}`,
        kind: "meta",
        tone: "text-sky",
        label: "qa",
        body: event.action || "",
      });
      return;
    }
    if (event.type === "node_status") {
      items.push({
        key: `node-${index}`,
        kind: "meta",
        tone: toneFor(event.status || ""),
        label: event.node_id || "node",
        body: `${event.status || ""}  ${event.action || ""}`.trim(),
      });
      return;
    }
    if (event.type === "feature_status") {
      const err = (event.error || "").trim();
      const bodyErr =
        err.includes("GraphInterrupt") && !err.includes("database is locked")
          ? "Paused for approval."
          : err;
      items.push({
        key: `feat-${index}`,
        kind: bodyErr.includes("\n") ? "code" : bodyErr && looksLikeMarkdown(bodyErr) ? "markdown" : "meta",
        tone: toneFor(event.status || ""),
        label: "feature",
        body: `${event.status || ""}${bodyErr ? `\n${bodyErr}` : ""}`.trim(),
      });
      return;
    }
    if (event.type === "audit_card") {
      items.push({
        key: `audit-${index}`,
        kind: "meta",
        tone: "text-amber",
        label: `audit ${event.severity}`,
        body: `${event.table} ${event.check}: ${event.detail || ""}`,
      });
      return;
    }
    if (event.type === "artifact" && event.content) {
      items.push({
        key: `art-${index}`,
        kind: "markdown",
        tone: "text-paper",
        label: event.name || "artifact",
        body: String(event.content),
      });
    }
  });
  flushAssistant();
  return items;
}

function MarkdownBody({ text }: { text: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => <h1 className="mb-2 mt-3 text-base font-semibold text-paper">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-3 text-sm font-semibold text-paper">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-medium text-paper">{children}</h3>,
        p: ({ children }) => <p className="mb-2 text-[12px] leading-relaxed text-paper/90">{children}</p>,
        ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 text-[12px] text-paper/90">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 text-[12px] text-paper/90">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        strong: ({ children }) => <strong className="font-semibold text-paper">{children}</strong>,
        a: ({ href, children }) => (
          <a href={href} className="text-sky underline underline-offset-2" target="_blank" rel="noreferrer">
            {children}
          </a>
        ),
        code: ({ className, children }) => {
          const block = Boolean(className);
          if (block) {
            return (
              <code className="block overflow-x-auto rounded bg-panel2 p-2 font-mono text-[11px] text-mint">{children}</code>
            );
          }
          return <code className="rounded bg-panel2 px-1 py-0.5 font-mono text-[11px] text-gold">{children}</code>;
        },
        pre: ({ children }) => <pre className="mb-2 overflow-x-auto rounded border border-line bg-panel2 p-2">{children}</pre>,
        table: ({ children }) => (
          <div className="mb-2 overflow-x-auto">
            <table className="w-full border-collapse text-left text-[11px]">{children}</table>
          </div>
        ),
        th: ({ children }) => <th className="border border-line bg-panel2 px-2 py-1 font-medium">{children}</th>,
        td: ({ children }) => <td className="border border-line px-2 py-1 align-top">{children}</td>,
      }}
    >
      {text}
    </Markdown>
  );
}

const STICK_BOTTOM_PX = 80;

export function StreamPanel({ events, epoch }: { events: JedocEvent[]; epoch: number }) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const stickToBottom = useRef(true);
  const feed = useMemo(() => buildFeed(events), [events]);

  useEffect(() => {
    const node = scroller.current;
    if (!node || !stickToBottom.current) return;
    node.scrollTop = node.scrollHeight;
  }, [epoch, feed.length]);

  return (
    <div className="flex h-full max-h-full min-h-0 min-w-0 flex-col overflow-hidden border-r border-line">
      <div className="flex shrink-0 items-center justify-between border-b border-line px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">Live agent stream</span>
        <span className="font-mono text-[10px] text-muted">{events.length} events</span>
      </div>
      <div
        ref={scroller}
        className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
        onScroll={(event) => {
          const node = event.currentTarget;
          const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
          stickToBottom.current = distance <= STICK_BOTTOM_PX;
        }}
      >
        <div className="space-y-2 px-3 py-3">
          {feed.length === 0 && (
            <p className="font-mono text-[11px] text-muted">Waiting for agent activity…</p>
          )}
          {feed.map((item) => (
            <article key={item.key} className="rounded border border-line/70 bg-panel/40 px-2.5 py-2">
              <div className={`mb-1 font-mono text-[10px] uppercase tracking-wider ${item.tone}`}>{item.label}</div>
              {item.kind === "markdown" ? (
                <MarkdownBody text={item.body} />
              ) : item.kind === "code" ? (
                <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] text-mint">{item.body}</pre>
              ) : (
                <p className={`whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed ${item.tone}`}>
                  {item.body}
                </p>
              )}
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
