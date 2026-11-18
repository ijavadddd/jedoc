"use client";

import { useState } from "react";
import type { GitProject } from "../types";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

interface Props {
  projects: GitProject[];
  root: string;
  projectPath: string;
  branch: string;
  branches: string[];
  dirty: boolean;
  useWorktree: boolean;
  workspace: string;
  disabled: boolean;
  browsing: boolean;
  onBrowse: () => void;
  onProject: (path: string) => void;
  onBranch: (branch: string) => void;
  onWorktree: (value: boolean) => void;
  onApply: () => void;
}

export function TargetBar(props: Props) {
  const [custom, setCustom] = useState("");
  const known = props.projects.some((item) => item.path === props.projectPath);
  const selectValue = !props.projectPath ? "none" : known ? props.projectPath : "custom";

  return (
    <div className="flex shrink-0 flex-wrap items-end gap-2 border-b border-border bg-card px-3 py-2">
      <div className="min-w-[220px] flex-1 space-y-1">
        <Label>Project folder</Label>
        <div className="flex gap-2">
          <Button size="sm" disabled={props.browsing} onClick={props.onBrowse} type="button">
            {props.browsing ? "Opening…" : "Choose folder"}
          </Button>
          <span className="min-w-0 flex-1 truncate self-center font-mono text-[11px]">{props.projectPath || "No folder selected"}</span>
        </div>
      </div>
      <div className="min-w-[180px] space-y-1">
        <Label>Known repos</Label>
        <Select
          value={selectValue}
          onValueChange={(value) => {
            if (value === "custom" || value === "none") {
              props.onProject("");
              return;
            }
            props.onProject(value);
          }}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select a git project" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Select a git project</SelectItem>
            {props.projects.map((item) => (
              <SelectItem key={item.path} value={item.path}>
                {item.name} · {item.branch || "detached"}
              </SelectItem>
            ))}
            <SelectItem value="custom">Other path…</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {selectValue === "custom" && (
        <div className="min-w-[240px] flex-1 space-y-1">
          <Label>Path</Label>
          <Input
            className="h-8 font-mono text-[11px]"
            placeholder={props.root}
            value={custom || props.projectPath}
            onChange={(event) => setCustom(event.target.value)}
            onBlur={() => {
              if (custom.trim()) props.onProject(custom.trim());
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && custom.trim()) props.onProject(custom.trim());
            }}
          />
        </div>
      )}
      <div className="min-w-[160px] space-y-1">
        <Label>Branch</Label>
        <Select value={props.branch || "none"} disabled={!props.projectPath} onValueChange={(value) => props.onBranch(value === "none" ? "" : value)}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Branch" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Branch</SelectItem>
            {props.branches.map((item) => (
              <SelectItem key={item} value={item}>
                {item}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Label className="mb-2 flex items-center gap-2 text-xs text-foreground">
        <Checkbox checked={props.useWorktree} onCheckedChange={(value) => props.onWorktree(value === true)} />
        Use worktree
      </Label>
      <Button className="mb-0.5" size="sm" disabled={props.disabled || !props.projectPath || !props.branch} onClick={props.onApply} type="button">
        Set checkout
      </Button>
      <p className="mb-1 min-w-[220px] flex-1 truncate font-mono text-[10px] text-muted-foreground">
        {props.useWorktree ? "Isolated worktree" : "Project checkout"}
        {props.dirty ? " · dirty tree" : ""}
        {props.workspace ? ` · ${props.workspace}` : ""}
      </p>
    </div>
  );
}
