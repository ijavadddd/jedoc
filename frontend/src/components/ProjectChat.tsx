"use client";

import { Bug, Check, ChevronDown, History, Infinity, List, MessageSquare, Mic, Orbit, Paperclip, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { api } from "../api";
import type { FileChange, ProviderAccount } from "../types";
import { FileChanges } from "./FileChanges";
import { Button } from "./ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "./ui/dropdown-menu";
import { ScrollArea } from "./ui/scroll-area";

type ChatMode = "agent" | "plan" | "debug" | "multitask" | "ask";

interface ChatMessage {
  id: number | string;
  role: string;
  content: string;
  thinking?: string;
  mode?: string;
  files?: FileChange[];
}

interface ThreadSummary {
  id: string;
  title: string;
  updated_at: string;
  active?: boolean;
}

interface History {
  workspace: string;
  thread_id: string;
  chat_id: string;
  title?: string;
  execution_mode: string;
  messages: ChatMessage[];
  threads?: ThreadSummary[];
  files?: FileChange[];
}

interface Props {
  workspace: string;
  providers: ProviderAccount[];
  width: number;
  onClose: () => void;
}

const MODES: { id: ChatMode; label: string; hint?: string; icon: typeof Infinity }[] = [
  { id: "agent", label: "Agent", hint: "Ctrl+I", icon: Infinity },
  { id: "plan", label: "Plan", icon: List },
  { id: "debug", label: "Debug", icon: Bug },
  { id: "multitask", label: "Multitask", icon: Orbit },
  { id: "ask", label: "Ask", icon: MessageSquare },
];

export function ProjectChat({ workspace, providers, width, onClose }: Props) {
  const cursor = providers.find((item) => item.id === "cursor");
  const models = cursor?.models ?? [];
  const [mode, setMode] = useState<ChatMode>("agent");
  const [autoModel, setAutoModel] = useState(true);
  const [model, setModel] = useState("");
  const [modelQuery, setModelQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [threadId, setThreadId] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!workspace) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    api<History>(`/api/project-chat?workspace=${encodeURIComponent(workspace)}`)
      .then((payload) => {
        if (!cancelled) showHistory(payload);
      })
      .catch(() => {
        if (!cancelled) {
          setMessages([]);
          setThreads([]);
          setThreadId("");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [workspace]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages, busy]);

  function showHistory(payload: History) {
    setThreadId(payload.thread_id || "");
    setThreads(payload.threads || []);
    setMessages(payload.messages.filter((item) => !item.content.includes("This reply is simulated because Jedoc is not calling the provider.")));
  }

  const visibleModels = models.filter((item) => item.toLowerCase().includes(modelQuery.trim().toLowerCase()));
  const modelLabel = model || models[0] || "Auto";
  const activeMode = MODES.find((item) => item.id === mode) ?? MODES[0];

  async function send(explicit?: string) {
    const text = (explicit ?? draft).trim();
    if (!text || !workspace || busy) return;
    setDraft("");
    setBusy(true);
    const pending = Date.now();
            setMessages((current) => [
      ...current,
      { id: `user-${pending}`, role: "user", content: text, mode },
      { id: `assistant-${pending}`, role: "assistant", content: "", thinking: "Thinking…", mode },
    ]);
    try {
      const response = await fetch("/api/project-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace, message: text, mode, model: autoModel ? "" : model, provider: "cursor", thread_id: threadId }),
      });
      if (!response.ok || !response.body) {
        let detail = response.statusText;
        try {
          const payload = (await response.json()) as { detail?: string };
          detail = payload.detail || detail;
        } catch {
          detail = (await response.text()) || detail;
        }
        throw new Error(detail || "No provider found");
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assembled = "";
      let finished = false;
      while (!finished) {
        const step = await reader.read();
        if (step.done) break;
        buffer += decoder.decode(step.value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((item) => item.startsWith("data:"));
          if (!line) continue;
          const event = JSON.parse(line.slice(5).trim()) as {
            type?: string;
            text?: string;
            content?: string;
            detail?: string;
            thread_id?: string;
            files?: FileChange[];
          };
          if (event.type === "ack" && event.thread_id) setThreadId(event.thread_id);
          if (event.type === "thinking" && event.text) {
            const piece = event.text;
            flushSync(() => {
              setMessages((current) =>
                current.map((item) =>
                  item.id === `assistant-${pending}`
                    ? { ...item, thinking: `${item.thinking && item.thinking !== "Thinking…" ? item.thinking : ""}${piece}` }
                    : item,
                ),
              );
            });
            await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
          } else if (event.type === "delta" && event.text) {
            assembled += event.text;
            const next = assembled;
            flushSync(() => {
              setMessages((current) => current.map((item) => (item.id === `assistant-${pending}` ? { ...item, content: next } : item)));
            });
            await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
          } else if (event.type === "files" && event.files) {
            const nextFiles = event.files;
            setMessages((current) => current.map((item) => (item.id === `assistant-${pending}` ? { ...item, files: nextFiles } : item)));
          } else if (event.type === "done" && event.content) {
            const next = event.content;
            const nextFiles = event.files;
            setMessages((current) =>
              current.map((item) => (item.id === `assistant-${pending}` ? { ...item, content: next, files: nextFiles || item.files } : item)),
            );
            finished = true;
          } else if (event.type === "error") {
            throw new Error(event.detail || "No provider found");
          }
        }
      }
      await reader.cancel().catch(() => undefined);
    } catch (err) {
      const raw = err instanceof Error && err.message ? err.message : "";
      const dropped = /network error|failed to fetch|networkerror|terminated/i.test(raw);
      setMessages((current) =>
        current.flatMap((item) => {
          if (item.id !== `assistant-${pending}`) return [item];
          if (item.content.trim()) return [item];
          return [{ ...item, role: "error", content: dropped ? "The connection dropped before Cursor finished. Send it again." : raw || "No provider found" }];
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  async function newChat() {
    if (!workspace || busy) return;
    const payload = await api<History>("/api/project-chat/new", { method: "POST", body: JSON.stringify({ workspace }) });
    showHistory(payload);
  }

  async function openThread(id: string) {
    if (!workspace || busy || id === threadId) return;
    const payload = await api<History>("/api/project-chat/open", { method: "POST", body: JSON.stringify({ workspace, thread_id: id }) });
    showHistory(payload);
  }

  function attachFiles(files: FileList | null) {
    if (!files?.length) return;
    const names = Array.from(files).map((file) => `@${file.name}`);
    setDraft((current) => (current ? `${current} ${names.join(" ")}` : names.join(" ")));
  }

  return (
    <aside className="flex h-full min-h-0 shrink-0 flex-col bg-[#1e2024] text-[#d7dbe3]" style={{ width }}>
      <div className="flex items-center justify-between gap-2 px-3 py-2 text-[11px] text-[#8b93a1]">
        <span className="truncate">{workspace ? workspace.split("/").filter(Boolean).pop() : "No folder"}</span>
        <div className="flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-6 px-2 text-[11px] text-[#8b93a1]" disabled={!workspace || busy} type="button">
                <History className="mr-1 h-3 w-3" />
                History
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="bottom" align="end" className="w-64 border-[#3a3f4b] bg-[#2a2e36] p-1 text-[#d7dbe3]">
              <div className="max-h-72 overflow-auto">
                {threads.length === 0 ? (
                  <div className="px-2 py-1.5 text-xs text-[#8b93a1]">No earlier chats</div>
                ) : (
                  threads.map((thread) => (
                    <DropdownMenuItem key={thread.id} className="items-start focus:bg-[#353a44]" onSelect={() => void openThread(thread.id)}>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm">{thread.title || "New chat"}</span>
                        <span className="block text-[10px] text-[#8b93a1]">{thread.updated_at ? new Date(thread.updated_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""}</span>
                      </span>
                      {thread.id === threadId && <Check className="mt-0.5 h-3.5 w-3.5" />}
                    </DropdownMenuItem>
                  ))
                )}
              </div>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-[11px] text-[#8b93a1]" disabled={!workspace || busy} onClick={() => void newChat()} type="button">
            New chat
          </Button>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-[11px] text-[#8b93a1]" onClick={onClose} type="button">
            Minimize
          </Button>
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2 px-3 py-3">
          {messages.map((message) => {
            const mine = message.role === "user";
            const failed = message.role === "error";
            return (
              <div key={message.id} className={mine ? "flex justify-end" : "flex justify-start"}>
                <div className="flex max-w-[85%] flex-col gap-1">
                {message.thinking ? <p className="whitespace-pre-wrap text-xs leading-snug text-[#8b93a1]">{message.thinking}</p> : null}
                {(message.content || !message.thinking || failed) && (
                  <div
                    className={
                      failed
                        ? "rounded-2xl border border-[#f07178]/40 bg-[#f07178]/10 px-3 py-2 text-sm text-[#f07178]"
                        : mine
                          ? "rounded-2xl rounded-br-md bg-[#3a4254] px-3 py-2 text-sm text-[#e7ecf3]"
                          : "rounded-2xl rounded-bl-md border border-[#3a3f4b] bg-[#16181d] px-3 py-2 text-sm leading-relaxed text-[#c5ccd6]"
                    }
                  >
                    <div className="whitespace-pre-wrap">{message.content || (busy && message.role === "assistant" ? "…" : "")}</div>
                  </div>
                )}
                {!mine && message.files?.length ? <FileChanges files={message.files} dark /> : null}
                </div>
              </div>
            );
          })}
          <div ref={bottom} />
        </div>
      </ScrollArea>
      <form
        className="px-3 pb-3"
        onSubmit={(event) => {
          event.preventDefault();
          const field = event.currentTarget.querySelector("textarea");
          void send(field?.value);
        }}
      >
        <div className="rounded-xl border border-[#3a3f4b] bg-[#16181d] px-3 pb-2 pt-3 shadow-panel">
          <textarea
            value={draft}
            rows={3}
            placeholder="Plan, Build, / for skills, @ for context"
            disabled={!workspace || busy}
            className="max-h-40 w-full resize-none bg-transparent text-sm text-[#e7ecf3] outline-none placeholder:text-[#6d7585] disabled:opacity-50"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send(event.currentTarget.value);
              }
            }}
          />
          <div className="mt-1 flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="inline-flex h-7 items-center gap-1.5 rounded-full bg-[#2a2e36] px-2.5 text-xs text-[#d7dbe3]" type="button">
                  <activeMode.icon className="h-3.5 w-3.5" />
                  {activeMode.label}
                  <ChevronDown className="h-3 w-3 text-[#8b93a1]" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="top" align="start" className="w-52 border-[#3a3f4b] bg-[#2a2e36] p-1 text-[#d7dbe3]">
                {MODES.map((item) => (
                  <DropdownMenuItem key={item.id} className="gap-2 focus:bg-[#353a44]" onSelect={() => setMode(item.id)}>
                    <item.icon className="h-3.5 w-3.5 text-[#8b93a1]" />
                    <span className="flex-1">{item.label}</span>
                    {item.hint && <span className="text-[10px] text-[#8b93a1]">{item.hint}</span>}
                    {mode === item.id && <Check className="h-3.5 w-3.5" />}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="inline-flex h-7 max-w-[150px] items-center gap-1 rounded-md px-2 text-xs text-[#d7dbe3]" type="button">
                  <span className="truncate">{modelLabel}</span>
                  <ChevronDown className="h-3 w-3 shrink-0 text-[#8b93a1]" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="top" align="start" className="w-64 border-[#3a3f4b] bg-[#2a2e36] p-1 text-[#d7dbe3]">
                <div className="flex items-center gap-2 px-2 py-1.5">
                  <Search className="h-3.5 w-3.5 text-[#8b93a1]" />
                  <input
                    value={modelQuery}
                    placeholder="Search models"
                    className="w-full bg-transparent text-sm outline-none placeholder:text-[#8b93a1]"
                    onChange={(event) => setModelQuery(event.target.value)}
                    onKeyDown={(event) => event.stopPropagation()}
                  />
                </div>
                <DropdownMenuSeparator className="bg-[#3a3f4b]" />
                <button
                  className="flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-left text-sm hover:bg-[#353a44]"
                  type="button"
                  onClick={() => {
                    setAutoModel((value) => !value);
                  }}
                >
                  Auto
                  <span className={`relative h-4 w-7 rounded-full ${autoModel ? "bg-[#d7dbe3]" : "bg-[#3a3f4b]"}`}>
                    <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-[#16181d] transition-all ${autoModel ? "left-3.5" : "left-0.5"}`} />
                  </span>
                </button>
                <div className="max-h-56 overflow-auto">
                  {visibleModels.map((item) => (
                    <DropdownMenuItem
                      key={item}
                      className="focus:bg-[#353a44]"
                      onSelect={() => {
                        setModel(item);
                        setAutoModel(false);
                      }}
                    >
                      <span className="flex-1 truncate">{item}</span>
                      {!autoModel && model === item && <Check className="h-3.5 w-3.5" />}
                    </DropdownMenuItem>
                  ))}
                </div>
                <DropdownMenuSeparator className="bg-[#3a3f4b]" />
                <div className="px-2 py-1.5 text-xs text-[#8b93a1]">{visibleModels.length ? "More models" : "No provider models"}</div>
              </DropdownMenuContent>
            </DropdownMenu>
            <div className="ml-auto flex items-center gap-0.5">
              <input ref={fileInput} className="hidden" type="file" multiple onChange={(event) => attachFiles(event.target.files)} />
              <button className="inline-flex h-7 w-7 items-center justify-center rounded-md text-[#8b93a1] hover:bg-[#2a2e36] hover:text-[#d7dbe3]" type="button" onClick={() => fileInput.current?.click()} aria-label="Attach">
                <Paperclip className="h-3.5 w-3.5" />
              </button>
              <button className="inline-flex h-7 w-7 items-center justify-center rounded-md text-[#8b93a1] hover:bg-[#2a2e36] hover:text-[#d7dbe3]" type="button" aria-label="Voice">
                <Mic className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      </form>
    </aside>
  );
}
