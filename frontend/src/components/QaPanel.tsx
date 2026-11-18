"use client";

import type { AuditCard, QaProgress } from "../types";
import { Badge } from "./ui/badge";
import { Card, CardContent } from "./ui/card";

function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

export function QaPanel({ progress, cards }: { progress: QaProgress | null; cards: AuditCard[] }) {
  const duration = progress?.duration_s ?? progress?.configured_duration_s ?? 600;
  const elapsed = progress?.elapsed_s ?? 0;
  const ratio = duration > 0 ? Math.min(1, elapsed / duration) : 0;
  return (
    <div className="flex h-full min-w-0 flex-col bg-panel">
      <div className="border-b border-line px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted">
        QA and data audit
      </div>
      <div className="border-b border-line px-3 py-3">
        <div className="flex items-end justify-between">
          <div>
            <div className="font-mono text-lg text-paper">
              {clock(elapsed)} <span className="text-xs text-muted">/ {clock(duration)}</span>
            </div>
            <p className="mt-1 text-[11px] text-muted">{progress?.action || "The 10-minute window starts with the QA node."}</p>
          </div>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded bg-panel2">
          <div className="h-full bg-gold" style={{ width: `${ratio * 100}%` }} />
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
        {cards.length === 0 && <p className="text-xs text-muted">Database cards appear when the auditor runs integrity, foreign-key, and precision checks.</p>}
        {cards.map((card, index) => (
          <Card key={`${card.table}-${card.check}-${index}`}>
            <CardContent className="p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[11px]">{card.table}</span>
              <Badge
                variant="outline"
                className={card.severity === "high" ? "text-coral" : card.severity === "info" ? "text-sky" : "text-amber"}
              >
                {card.severity} · {card.check}
              </Badge>
            </div>
            <p className="mt-1 text-[11px] leading-snug text-muted-foreground">{card.detail}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
