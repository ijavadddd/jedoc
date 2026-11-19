"use client";

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "./ui/dropdown-menu";

interface Props {
  x: number;
  y: number;
  name: string;
  enabled: boolean;
  canDelete: boolean;
  canSkip: boolean;
  onEdit: () => void;
  onToggle: () => void;
  onSkip: () => void;
  onDelete: () => void;
  onClose: () => void;
}

export function NodeContextMenu(props: Props) {
  const left = Math.max(8, Math.min(props.x, window.innerWidth - 8));
  const top = Math.max(8, Math.min(props.y, window.innerHeight - 8));
  return (
    <DropdownMenu open onOpenChange={(open) => !open && props.onClose()}>
      <DropdownMenuTrigger asChild>
        <button aria-hidden className="fixed h-px w-px p-0 opacity-0" style={{ left, top }} tabIndex={-1} type="button" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-44" side="bottom">
        <DropdownMenuLabel>{props.name}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={props.onEdit}>Edit agent</DropdownMenuItem>
        <DropdownMenuItem onSelect={props.onToggle}>{props.enabled ? "Disable agent" : "Enable agent"}</DropdownMenuItem>
        <DropdownMenuItem
          disabled={!props.canSkip}
          title={props.canSkip ? "Mark this agent PASS and continue" : "Start or resume the feature to skip an agent"}
          onSelect={props.onSkip}
        >
          Skip agent
        </DropdownMenuItem>
        <DropdownMenuItem
          className="text-destructive focus:text-destructive"
          disabled={!props.canDelete}
          title={props.canDelete ? "Remove this agent and its edges" : "Finish the run before deleting an agent"}
          onSelect={props.onDelete}
        >
          Delete agent
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
