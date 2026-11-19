"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { JedocEvent } from "../types";
import { Button } from "./ui/button";

type Message = {
  key: string;
  kind: "assistant" | "notice";
  label: string;
  body: string;
  tone: string;
};

type LiveLine = {
  label: string;
  body: string;
  tone: string;
};

function toneFor(kind: string): string {
  if (kind === "thinking") return "text-muted";
  if (kind === "assistant") return "text-paper";
  if (kind === "shell") return "text-mint";
  if (kind === "mcp" || kind === "tool_call") return "text-sky";
  if (kind === "system") return "text-amber";
  if (kind === "error" || kind === "failed") return "text-coral";
  if (kind === "completed" || kind === "paused") return "text-mint";
  return "text-muted";
}

function looksLikeMarkdown(text: string): boolean {
  return /(^#{1,6}\s)|(```)|(\*\*[^*]+\*\*)|(^\s*[-*]\s)|(^\s*\d+\.\s)|(\[[^\]]+\]\([^)]+\))/m.test(text);
}

function isEphemeralSystem(text: string): boolean {
  return /cursor is working|still running|launching cursor|opening cursor|preparing workspace|mapping the repository|idle \(limit/i.test(
    text,
  );
}

/** Permanent messages = agent replies (+ rare notices). Thinking/tools/actions collapse to one live line. */
function buildFeed(events: JedocEvent[]): { messages: Message[]; live: LiveLine | null } {
  const messages: Message[] = [];
  let assistant = "";
  let assistantKey = "";
  let live: LiveLine | null = null;

  const flushAssistant = () => {
    if (!assistant.trim()) {
      assistant = "";
      assistantKey = "";
      return;
    }
    messages.push({
      key: assistantKey || `assistant-${messages.length}`,
      kind: "assistant",
      label: "assistant",
      body: assistant,
      tone: toneFor("assistant"),
    });
    assistant = "";
    assistantKey = "";
  };

  const setLive = (label: string, body: string, toneKind: string) => {
    const text = body.trim();
    if (!text) return;
    live = { label, body: text, tone: toneFor(toneKind) };
  };

  events.forEach((event, index) => {
    if (event.type === "stream") {
      const kind = event.kind || "log";
      const text = event.text || event.detail || "";
      if (kind === "assistant") {
        if (!assistantKey) assistantKey = `assistant-${event.id || index}`;
        assistant += text;
        live = null;
        return;
      }
      flushAssistant();
      if (kind === "thinking") {
        setLive("thinking", text || "…", "thinking");
        return;
      }
      if (kind === "shell") {
        setLive("$", text || event.name || "shell", "shell");
        return;
      }
      if (kind === "tool_call" || kind === "mcp") {
        const label = kind === "mcp" ? `mcp ${event.name || "tool"}` : event.name || "tool";
        setLive(label, text || event.subtype || "…", kind);
        return;
      }
      if (kind === "session") {
        setLive("session", text, "system");
        return;
      }
      if (kind === "system") {
        if (event.level === "error") {
          messages.push({
            key: `err-${event.id || index}`,
            kind: "notice",
            label: "error",
            body: text,
            tone: toneFor("error"),
          });
          live = null;
          return;
        }
        if (isEphemeralSystem(text)) {
          setLive("status", text, "system");
          return;
        }
        // Durable system notes (restart, circuit heal, etc.) stay readable.
        messages.push({
          key: `sys-${event.id || index}`,
          kind: "notice",
          label: "system",
          body: text,
          tone: toneFor("system"),
        });
        return;
      }
      if (text.trim()) setLive(kind, text, kind);
      return;
    }

    flushAssistant();
    if (event.type === "qa_progress") {
      setLive("qa", event.action || "", "system");
      return;
    }
    if (event.type === "node_status") {
      setLive(event.node_id || "node", `${event.status || ""}  ${event.action || ""}`.trim(), event.status || "system");
      return;
    }
    if (event.type === "feature_status") {
      const status = event.status || "";
      if (status === "running") {
        setLive("feature", "running", status);
        return;
      }
      const err = (event.error || "").trim();
      const bodyErr =
        err.includes("GraphInterrupt") && !err.includes("database is locked") ? "Paused for approval." : err;
      messages.push({
        key: `feat-${event.id || index}`,
        kind: "notice",
        label: "feature",
        body: `${status}${bodyErr ? `\n${bodyErr}` : ""}`.trim(),
        tone: toneFor(status),
      });
      live = null;
      return;
    }
    if (event.type === "audit_card") {
      setLive(`audit ${event.severity}`, `${event.table} ${event.check}: ${event.detail || ""}`, "system");
      return;
    }
    if (event.type === "artifact" && event.content) {
      // Artifacts stay in the inspector; don't dump them into the stream.
      setLive("artifact", event.name || "saved", "system");
    }
  });

  // Keep an in-progress assistant reply as a real message so it can be read while streaming.
  if (assistant.trim()) {
    messages.push({
      key: assistantKey || `assistant-live`,
      kind: "assistant",
      label: "assistant",
      body: assistant,
      tone: toneFor("assistant"),
    });
  }

  return { messages, live };
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

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="h-6 px-2 font-mono text-[10px] text-muted hover:text-paper"
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        });
      }}
    >
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

const STICK_BOTTOM_PX = 96;

export function StreamPanel({ events }: { events: JedocEvent[]; epoch?: number }) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const stickToBottom = useRef(true);
  const { messages, live } = useMemo(() => buildFeed(events), [events]);
  const lastAssistantLen = messages.filter((item) => item.kind === "assistant").at(-1)?.body.length ?? 0;

  useEffect(() => {
    const node = scroller.current;
    if (!node || !stickToBottom.current) return;
    node.scrollTop = node.scrollHeight;
  }, [messages.length, lastAssistantLen, live?.body]);

  return (
    <div className="flex h-full max-h-full min-h-0 min-w-0 flex-col overflow-hidden border-r border-line">
      <div className="flex shrink-0 items-center justify-between border-b border-line px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">Live agent stream</span>
        <span className="font-mono text-[10px] text-muted">{messages.length} messages</span>
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
          {messages.length === 0 && !live && (
            <p className="font-mono text-[11px] text-muted">Waiting for agent activity…</p>
          )}
          {messages.map((item) => (
            <article key={item.key} className="rounded border border-line/70 bg-panel/40 px-2.5 py-2">
              <div className="mb-1 flex items-center justify-between gap-2">
                <div className={`font-mono text-[10px] uppercase tracking-wider ${item.tone}`}>{item.label}</div>
                {item.kind === "assistant" && <CopyButton text={item.body} />}
              </div>
              {item.kind === "assistant" || looksLikeMarkdown(item.body) ? (
                <MarkdownBody text={item.body} />
              ) : (
                <p className={`whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed ${item.tone}`}>
                  {item.body}
                </p>
              )}
            </article>
          ))}
        </div>
      </div>
      {live && (
        <div className="shrink-0 border-t border-line bg-panel2/80 px-3 py-2">
          <div className={`font-mono text-[10px] uppercase tracking-wider ${live.tone}`}>{live.label}</div>
          <p className={`mt-0.5 line-clamp-3 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed ${live.tone}`}>
            {live.body}
          </p>
        </div>
      )}
    </div>
  );
}
