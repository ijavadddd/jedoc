"use client";

import { useState } from "react";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

interface Props {
  onDone: () => void;
  onBack: () => void;
}

const FOLDERS = [
  { id: "shop", name: "shop", branch: "main" },
  { id: "ledger", name: "ledger", branch: "feature/invoices" },
  { id: "notes", name: "notes", branch: "main" },
];

const STEPS = ["Folder", "Nodes", "Save", "Model", "Run"];

export function GuideToy({ onDone, onBack }: Props) {
  const [step, setStep] = useState(0);
  const [folder, setFolder] = useState<string | null>(null);
  const [worktree, setWorktree] = useState(true);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [selected, setSelected] = useState<string | null>(null);
  const [savedName, setSavedName] = useState("");
  const [saved, setSaved] = useState<string[]>([]);
  const [authorized, setAuthorized] = useState(false);
  const [model, setModel] = useState("");
  const [running, setRunning] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);

  function next() {
    setStep((value) => Math.min(STEPS.length - 1, value + 1));
  }

  function runToy() {
    const order = ["Architect", "Implementer", "Reviewer"];
    setLog([]);
    order.forEach((name, index) => {
      window.setTimeout(() => {
        setRunning(name);
        setLog((current) => [...current, `${name} finished`]);
        if (index === order.length - 1) {
          window.setTimeout(() => setRunning(null), 500);
        }
      }, index * 600);
    });
  }

  return (
    <div className="flex h-screen flex-col bg-ink text-paper">
      <header className="flex h-14 items-center gap-3 border-b border-line px-4">
        <Button variant="outline" size="sm" onClick={onBack} type="button">
          Home
        </Button>
        <div>
          <div className="text-sm font-medium">Practice guide</div>
          <div className="font-mono text-[10px] text-muted">A toy pipeline. Nothing here is saved.</div>
        </div>
        <div className="ml-auto flex gap-1">
          {STEPS.map((label, index) => (
            <Button
              key={label}
              variant={index === step ? "default" : "ghost"}
              size="sm"
              className="font-mono text-[10px]"
              onClick={() => setStep(index)}
              type="button"
            >
              {index + 1} {label}
            </Button>
          ))}
        </div>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-[280px_1fr]">
        <aside className="border-r border-line p-4 text-sm">
          {step === 0 && (
            <>
              <h2 className="font-medium">Choose a folder</h2>
              <p className="mt-2 text-xs leading-relaxed text-muted">
                On the real workstation this button opens the desktop folder dialog. Here, pick a toy repo.
              </p>
            </>
          )}
          {step === 1 && (
            <>
              <h2 className="font-medium">Drag a node</h2>
              <p className="mt-2 text-xs leading-relaxed text-muted">
                The canvas is the pipeline. Drag Implementer. The list on the left of the real app is where saved nodes stay findable.
              </p>
            </>
          )}
          {step === 2 && (
            <>
              <h2 className="font-medium">Save a node</h2>
              <p className="mt-2 text-xs leading-relaxed text-muted">
                Fields start empty. Type a name and save it. It shows up in the saved-node list.
              </p>
              <Input className="mt-3" placeholder="Agent name" value={savedName} onChange={(event) => setSavedName(event.target.value)} />
              <Button
                className="mt-2"
                size="sm"
                disabled={!savedName.trim()}
                onClick={() => {
                  setSaved((current) => [...current, savedName.trim()]);
                  setSavedName("");
                }}
                type="button"
              >
                Save node
              </Button>
              <ul className="mt-3 space-y-1">
                {saved.map((name) => (
                  <li key={name} className="rounded border border-line px-2 py-1 text-xs">
                    {name}
                  </li>
                ))}
              </ul>
            </>
          )}
          {step === 3 && (
            <>
              <h2 className="font-medium">Pick a model</h2>
              <p className="mt-2 text-xs leading-relaxed text-muted">
                Models appear after the provider is authorized. Until then the field stays empty.
              </p>
              <Button className="mt-3" variant="outline" size="sm" onClick={() => setAuthorized(true)} type="button">
                {authorized ? "Cursor authorized" : "Authorize Cursor"}
              </Button>
              <Select value={model || "none"} onValueChange={(value) => setModel(value === "none" ? "" : value)}>
                <SelectTrigger className="mt-3">
                  <SelectValue placeholder={authorized ? "Choose a model" : "No models yet"} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{authorized ? "Choose a model" : "No models yet"}</SelectItem>
                  {authorized && (
                    <>
                      <SelectItem value="composer-1.5">composer-1.5</SelectItem>
                      <SelectItem value="gpt-5">gpt-5</SelectItem>
                    </>
                  )}
                </SelectContent>
              </Select>
            </>
          )}
          {step === 4 && (
            <>
              <h2 className="font-medium">Watch a run</h2>
              <p className="mt-2 text-xs leading-relaxed text-muted">
                Start lights each node in order and writes a short log. The real run streams Cursor in the bottom dock.
              </p>
              <Button className="mt-3" size="sm" onClick={runToy} type="button">
                Start toy run
              </Button>
              <ul className="mt-3 space-y-1 font-mono text-[11px] text-muted">
                {log.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </>
          )}
          <div className="mt-6 flex gap-2">
            <Button variant="outline" size="sm" disabled={step === 0} onClick={() => setStep((value) => value - 1)} type="button">
              Back
            </Button>
            {step < STEPS.length - 1 ? (
              <Button variant="outline" size="sm" onClick={next} type="button">
                Next
              </Button>
            ) : (
              <Button size="sm" onClick={onDone} type="button">
                Open workstation
              </Button>
            )}
          </div>
        </aside>
        <div className="relative min-h-0 bg-ink p-8">
          {step === 0 && (
            <div className="mx-auto max-w-md rounded-xl border border-line bg-panel p-4">
              <div className="text-xs text-muted">Desktop folder dialog</div>
              <div className="mt-3 space-y-2">
                {FOLDERS.map((item) => (
                  <Button
                    key={item.id}
                    variant={folder === item.id ? "default" : "outline"}
                    className="h-auto w-full justify-between py-2"
                    onClick={() => setFolder(item.id)}
                    type="button"
                  >
                    <span>{item.name}</span>
                    <span className="font-mono text-[10px] opacity-80">{item.branch}</span>
                  </Button>
                ))}
              </div>
              <Label className="mt-3 flex items-center gap-2 text-xs text-foreground">
                <Checkbox checked={worktree} onCheckedChange={(value) => setWorktree(value === true)} />
                Use a worktree
              </Label>
              <p className="mt-3 font-mono text-[11px] text-muted">
                {folder ? `${folder} @ ${FOLDERS.find((item) => item.id === folder)?.branch}${worktree ? " · worktree" : ""}` : "No folder yet"}
              </p>
            </div>
          )}
          {step > 0 && (
            <div className="relative h-full">
              <ToyNode name="Architect" x={40} y={40} active={running === "Architect"} selected={selected === "Architect"} onSelect={() => setSelected("Architect")} />
              <ToyNode
                name="Implementer"
                x={220 + offset.x}
                y={40 + offset.y}
                active={running === "Implementer"}
                selected={selected === "Implementer"}
                onSelect={() => setSelected("Implementer")}
                onDrag={(dx, dy) => setOffset((current) => ({ x: current.x + dx, y: current.y + dy }))}
              />
              <ToyNode name="Reviewer" x={400} y={140} active={running === "Reviewer"} selected={selected === "Reviewer"} onSelect={() => setSelected("Reviewer")} />
              {model && (
                <div className="absolute bottom-4 left-4 rounded border border-line bg-panel px-2 py-1 font-mono text-[11px] text-sky">
                  cursor · {model}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ToyNode({
  name,
  x,
  y,
  active,
  selected,
  onSelect,
  onDrag,
}: {
  name: string;
  x: number;
  y: number;
  active: boolean;
  selected: boolean;
  onSelect: () => void;
  onDrag?: (dx: number, dy: number) => void;
}) {
  return (
    <Button
      variant="outline"
      className={`absolute h-auto w-36 justify-start px-3 py-3 text-left text-sm ${selected ? "border-primary" : ""} ${active ? "ring-1 ring-sky" : ""}`}
      style={{ left: x, top: y }}
      onClick={onSelect}
      onPointerDown={(event) => {
        if (!onDrag) return;
        event.preventDefault();
        event.stopPropagation();
        let lastX = event.clientX;
        let lastY = event.clientY;
        const move = (next: PointerEvent) => {
          onDrag(next.clientX - lastX, next.clientY - lastY);
          lastX = next.clientX;
          lastY = next.clientY;
        };
        const up = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      }}
      type="button"
    >
      <div>
        <div>{name}</div>
        <div className="mt-1 font-mono text-[10px] text-muted-foreground">{active ? "RUNNING" : "IDLE"}</div>
      </div>
    </Button>
  );
}
