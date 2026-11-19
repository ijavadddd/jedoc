"use client";

import { useState } from "react";
import type { ProviderAccount } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

interface Props {
  providers: ProviderAccount[];
  onSave: (input: { api_key?: string; clear_api_key?: boolean; endpoint?: string }) => Promise<void>;
  onRefresh: () => Promise<void>;
  onLogin: () => Promise<{ url?: string; detail?: string; started?: boolean }>;
  onLogout: () => Promise<void>;
}

export function ProvidersView({ providers, onSave, onRefresh, onLogin, onLogout }: Props) {
  const cursor = providers.find((item) => item.id === "cursor") ?? null;
  const [apiKey, setApiKey] = useState("");
  const [endpoint, setEndpoint] = useState(cursor?.endpoint ?? "");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  async function run(label: string, action: () => Promise<string>) {
    setBusy(label);
    setMessage("");
    try {
      setMessage(await action());
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy("");
    }
  }

  if (!cursor) {
    return <div className="p-6 text-sm text-muted-foreground">No AI providers are configured.</div>;
  }

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-3xl flex-col gap-4 overflow-auto p-6">
      <div>
        <h2 className="text-lg font-medium">AI providers</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Cursor is the execution engine. Authorize the CLI, then its models show up on each agent node.
        </p>
      </div>
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Cursor</CardTitle>
            <CardDescription className="mt-1 font-mono">
              {cursor.installed === false
                ? "agent is not on PATH (use ./start.sh on the host; Docker has no Cursor CLI)"
                : "agent CLI"}
            </CardDescription>
          </div>
          <Badge variant="outline" className={cursor.authenticated ? "border-mint/40 text-mint" : "border-amber/50 text-amber"}>
            {cursor.authenticated ? "Authorized" : "Not authorized"}
          </Badge>
        </CardHeader>
        <CardContent>
        {cursor.auth_detail && <p className="mt-3 text-xs leading-relaxed text-paper/90">{cursor.auth_detail}</p>}
        {cursor.has_api_key && <p className="mt-2 font-mono text-[11px] text-muted-foreground">API key {cursor.api_key_hint}</p>}
        {cursor.models_error && <p className="mt-2 text-xs text-coral">{cursor.models_error}</p>}
        <div className="mt-4 grid gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cursor-key">API key</Label>
            <Input
              id="cursor-key"
              className="font-mono text-xs"
              type="password"
              autoComplete="off"
              placeholder={cursor.has_api_key ? "Leave blank to keep the saved key" : "CURSOR_API_KEY"}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cursor-endpoint">API endpoint</Label>
            <Input
              id="cursor-endpoint"
              className="font-mono text-xs"
              placeholder="https://api2.cursor.sh"
              value={endpoint}
              onChange={(event) => setEndpoint(event.target.value)}
            />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={Boolean(busy)}
            onClick={() =>
              void run("save", async () => {
                await onSave({ api_key: apiKey.trim() || undefined, endpoint });
                setApiKey("");
                return "Cursor config saved.";
              })
            }
            type="button"
          >
            Save config
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={Boolean(busy)}
            onClick={() => void run("refresh", async () => {
              await onRefresh();
              return "Checked Cursor and refreshed models.";
            })}
            type="button"
          >
            Check and load models
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={Boolean(busy)}
            onClick={() =>
              void run("login", async () => {
                const result = await onLogin();
                if (result.url) return `Finish login: ${result.url}`;
                return result.detail || (result.started ? "Login started in the browser." : "Login did not start.");
              })
            }
            type="button"
          >
            Login with browser
          </Button>
          {cursor.has_api_key && (
            <Button
              variant="outline"
              size="sm"
              disabled={Boolean(busy)}
              onClick={() =>
                void run("clear", async () => {
                  await onSave({ clear_api_key: true, endpoint });
                  return "Saved API key cleared.";
                })
              }
              type="button"
            >
              Clear key
            </Button>
          )}
          <Button
            variant="destructive"
            size="sm"
            disabled={Boolean(busy)}
            onClick={() =>
              void run("logout", async () => {
                if (!window.confirm("Sign the Cursor CLI out of this machine?")) return "Logout cancelled.";
                await onLogout();
                return "Cursor CLI signed out.";
              })
            }
            type="button"
          >
            Log out
          </Button>
        </div>
        {message && <p className="mt-3 text-xs text-paper/90">{message}</p>}
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Models</div>
          {cursor.models.length === 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">No models loaded yet. Authorize Cursor, then check the connection.</p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-1">
              {cursor.models.map((model) => (
                <li key={model}>
                  <Badge variant="outline" className="font-mono normal-case text-sky">
                    {model}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
        </CardContent>
      </Card>
    </div>
  );
}
