"use client";

import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

interface Props {
  onEnter: () => void;
  onGuide: () => void;
}

const STEPS = [
  ["1", "Choose a folder", "The desktop dialog picks the git project. Then choose a branch, with or without a worktree."],
  ["2", "Find the nodes", "Saved agents live in the node list. Click one to center it and open its settings."],
  ["3", "Authorize Cursor", "Providers loads the model list. New nodes and the inspector only offer those models."],
];

export function Landing({ onEnter, onGuide }: Props) {
  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex h-14 items-center gap-2 border-b border-border px-6">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-primary font-mono text-xs font-medium text-primary-foreground">Jd</span>
        <span className="text-sm font-medium">Jedoc</span>
      </header>
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center gap-10 px-6 py-10">
        <div className="max-w-xl">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-primary">Multi-agent workstation</p>
          <h1 className="mt-3 text-4xl font-medium leading-tight">Run a software pipeline you can see.</h1>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
            Jedoc points Cursor at a folder, then walks architect, tests, implementation, review, and QA as nodes on a canvas. Each node keeps its own chat until you mark the feature done.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button onClick={onEnter} type="button">
              Open workstation
            </Button>
            <Button variant="outline" onClick={onGuide} type="button">
              Practice with the guide
            </Button>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {STEPS.map(([step, title, body]) => (
            <Card key={step}>
              <CardHeader>
                <p className="font-mono text-[11px] text-primary">{step}</p>
                <CardTitle>{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="leading-relaxed">{body}</CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </main>
    </div>
  );
}
