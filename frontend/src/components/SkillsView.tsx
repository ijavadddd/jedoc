"use client";

import Editor from "@monaco-editor/react";
import { useMemo, useState } from "react";
import type { Skill } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

interface Props {
  skills: Skill[];
  workspace?: string;
  onToggle: (skillId: string, enabled: boolean) => Promise<void>;
  onSave: (skillId: string, path: string, content: string) => Promise<void>;
}

export function SkillsView({ skills, workspace, onToggle, onSave }: Props) {
  const [selected, setSelected] = useState(skills[0]?.id ?? "");
  const skill = skills.find((item) => item.id === selected) ?? skills[0];
  const [filePath, setFilePath] = useState(skill?.files[0]?.path ?? "SKILL.md");
  const file = skill?.files.find((item) => item.path === filePath) ?? skill?.files[0];
  const [draft, setDraft] = useState(file?.content ?? "");
  const [message, setMessage] = useState("");

  const activeKey = `${skill?.id}:${file?.path}`;
  const knownKey = useMemo(() => activeKey, [activeKey]);
  const [seen, setSeen] = useState(knownKey);
  if (seen !== knownKey && file) {
    setSeen(knownKey);
    setDraft(file.content);
    setFilePath(file.path);
  }

  if (!skill || !file) {
    return <div className="p-6 text-sm text-muted-foreground">No bundled skills were found.</div>;
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[320px_1fr]">
      <aside className="overflow-auto border-r border-border bg-card">
        {skills.map((item) => (
          <button
            key={item.id}
            className={`block w-full border-b border-border px-3 py-3 text-left ${item.id === skill.id ? "bg-accent" : "hover:bg-accent/50"}`}
            onClick={() => {
              setSelected(item.id);
              setFilePath(item.files[0]?.path ?? "SKILL.md");
              setMessage("");
            }}
            type="button"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm">{item.name}</span>
              <Badge variant="outline" className={item.enabled ? "text-mint" : ""}>
                {item.enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
            <p className="mt-1 text-[11px] leading-snug text-muted-foreground">{item.summary}</p>
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">{item.synced ? "Synced into the workspace" : "Not fully present in the workspace"}</p>
          </button>
        ))}
      </aside>
      <section className="flex min-h-0 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
          <h2 className="text-sm font-medium">{skill.name}</h2>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void onToggle(skill.id, !skill.enabled).then(() => setMessage(skill.enabled ? "Disabled" : "Enabled"))}
            type="button"
          >
            {skill.enabled ? "Disable" : "Enable"}
          </Button>
          <Select value={file.path} onValueChange={setFilePath}>
            <SelectTrigger className="h-8 w-auto min-w-40 font-mono text-[11px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {skill.files.map((item) => (
                <SelectItem key={item.path} value={item.path}>
                  {item.path}
                  {item.present_in_workspace ? " · in workspace" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="font-mono text-[10px] text-muted-foreground">{file.dest}</span>
          <Button
            className="ml-auto"
            size="sm"
            onClick={() =>
              void onSave(skill.id, file.path, draft)
                .then(() => setMessage("Saved"))
                .catch((err: unknown) => setMessage(err instanceof Error ? err.message : "Save failed"))
            }
            type="button"
          >
            Save file
          </Button>
        </div>
        <p className="px-3 py-1 text-[11px] text-muted-foreground">
          {workspace
            ? "Saving or toggling rewrites the workspace from the catalog. Nothing is downloaded."
            : "Open a feature to sync these files into a workspace."}{" "}
          {message}
        </p>
        <div className="min-h-0 flex-1">
          <Editor
            height="100%"
            theme="vs-dark"
            language={file.path.endsWith(".py") ? "python" : file.path.endsWith(".json") ? "json" : "markdown"}
            value={draft}
            onChange={(value) => setDraft(value ?? "")}
            options={{ fontFamily: "IBM Plex Mono", fontSize: 13, minimap: { enabled: false }, wordWrap: "on" }}
          />
        </div>
      </section>
    </div>
  );
}
