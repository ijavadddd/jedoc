"use client";

import { useEffect, useState } from "react";
import { api } from "../api";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";

interface Props {
  open: boolean;
  checkout: string;
  onClose: () => void;
  onCreate: (input: { name: string; prd: string; workspace_path?: string }) => Promise<void>;
}

export function FeatureDialog({ open, checkout, onClose, onCreate }: Props) {
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [prd, setPrd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setName("");
    setWorkspace("");
    setPrd("");
    setError("");
  }, [open]);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await onCreate({ name, prd, workspace_path: workspace.trim() || undefined });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the feature");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>New feature</DialogTitle>
          <DialogDescription>
            {checkout ? `Checkout: ${checkout}. PRD.md is written there.` : "No project selected. A fresh workspace is created, or use the path below."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 px-4">
          <div className="space-y-1.5">
            <Label htmlFor="feature-name">Name</Label>
            <Input id="feature-name" placeholder="Feature name" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="feature-workspace">Workspace path</Label>
            <Input
              id="feature-workspace"
              className="font-mono text-xs"
              placeholder={checkout ? "Ignored while a project is selected" : "Leave empty to create data/workspaces/…"}
              disabled={Boolean(checkout)}
              value={workspace}
              onChange={(event) => setWorkspace(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="feature-prd">PRD</Label>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  void api<{ markdown: string }>("/api/sample-prd")
                    .then((payload) => setPrd(payload.markdown))
                    .catch(() => setError("Could not load the sample PRD"))
                }
                type="button"
              >
                Load sample
              </Button>
            </div>
            <Textarea
              id="feature-prd"
              placeholder="Write the PRD, or load the sample."
              className="h-64 resize-y font-mono text-xs leading-relaxed"
              value={prd}
              onChange={(event) => setPrd(event.target.value)}
            />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button disabled={busy || !name.trim() || !prd.trim()} onClick={() => void submit()} type="button">
            {busy ? "Creating…" : "Create feature"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
