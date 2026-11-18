"use client";

import { useState } from "react";
import type { ProviderAccount } from "../types";
import { ModelSelect } from "./ModelSelect";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

interface Props {
  open: boolean;
  providers: ProviderAccount[];
  onClose: () => void;
  onCreate: (input: { display_name: string; role_type: string; cursor_mode: string; provider: string; model: string }) => Promise<void>;
}

const ROLES = ["custom", "architect", "tdd", "implementer", "reviewer", "qa_auditor"];
const MODES = ["agent", "plan", "ask"];

export function AgentDialog({ open, providers, onClose, onCreate }: Props) {
  const available = providers.filter((item) => item.enabled);
  const [name, setName] = useState("");
  const [role, setRole] = useState("custom");
  const [mode, setMode] = useState("agent");
  const [provider, setProvider] = useState(available[0]?.id || "cursor");
  const [model, setModel] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const account = providers.find((item) => item.id === provider);
  const models = account?.models ?? [];
  const choices = available.length ? available : [{ id: "cursor", name: "Cursor" }];

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await onCreate({ display_name: name.trim(), role_type: role, cursor_mode: mode, provider, model });
      setName("");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the agent");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add agent</DialogTitle>
          <DialogDescription>Models come from the providers you have authorized.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 px-4">
          <div className="space-y-1.5">
            <Label htmlFor="agent-name">Name</Label>
            <Input id="agent-name" placeholder="Name this agent" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label>Role</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Mode</Label>
              <Select value={mode} onValueChange={setMode}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MODES.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Provider</Label>
            <Select
              value={provider}
              onValueChange={(next) => {
                setProvider(next);
                setModel("");
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {choices.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Model</Label>
            <ModelSelect models={models} value={model} onChange={setModel} />
          </div>
          {account && !account.authenticated && (
            <p className="text-xs text-amber">Cursor is not authorized yet. Open Providers to log in or save an API key.</p>
          )}
          {account?.authenticated && models.length === 0 && (
            <p className="text-xs text-muted-foreground">No model catalog yet. Load models from Providers, or type a custom id.</p>
          )}
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button disabled={busy || !name.trim()} onClick={() => void submit()} type="button">
            {busy ? "Adding…" : "Add agent"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
