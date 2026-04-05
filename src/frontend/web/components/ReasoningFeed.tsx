"use client";

import * as React from "react";
import type { ScanStep } from "@/lib/types";
import { Card } from "./ui/card";

function sourceTone(source?: string): {
  border: string;
  chip: string;
  label: string;
} {
  switch (source) {
    case "claude":
      return {
        border: "border-violet-400",
        chip: "bg-violet-100 text-violet-700",
        label: "Claude",
      };
    case "browser-use":
      return {
        border: "border-emerald-400",
        chip: "bg-emerald-100 text-emerald-700",
        label: "browser-use",
      };
    default:
      return {
        border: "border-slate-300",
        chip: "bg-slate-100 text-slate-600",
        label: "worker",
      };
  }
}

export function ReasoningFeed({ steps }: { steps: ScanStep[] }) {
  const scrollRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [steps.length]);
  if (!steps.length) return null;
  return (
    <Card className="p-4">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Agent reasoning
      </p>
      <div
        ref={scrollRef}
        className="flex max-h-64 flex-col gap-2 overflow-y-auto pr-2"
      >
        {steps.map((s, i) => {
          const tone = sourceTone(s.source);
          return (
            <div
              key={`${s.step}-${i}`}
              className={`border-l-2 ${tone.border} pl-3 text-xs leading-snug`}
            >
              <div className="flex items-center gap-1.5">
                <span
                  className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${tone.chip}`}
                >
                  {tone.label}
                </span>
                <span className="font-medium text-slate-900">
                  {s.next_goal || s.evaluation || `step ${s.step}`}
                </span>
              </div>
              {s.memory && (
                <div className="mt-0.5 text-slate-500">{s.memory}</div>
              )}
              {s.actions && s.actions.length > 0 && (
                <div className="mt-1 font-mono text-[10px] text-slate-400">
                  → {s.actions.join(", ")}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
