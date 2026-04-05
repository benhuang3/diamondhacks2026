"use client";

import * as React from "react";
import type { ScanStep } from "@/lib/types";
import { Card } from "./ui/card";

const MAX_ENTRIES_PER_PANEL = 1;

const TARGET_LANE = "your store";
const MERGE_LANE = "discover: merge";
// Fixed order for the 4 discovery agents so the row stays stable across
// re-renders even as different agents start emitting at different times.
const DISCOVERY_LANES = [
  "discover: direct-alternatives",
  "discover: dtc-brands",
  "discover: shopify-stores",
  "discover: boutique",
];

function sourceTone(source?: string): { border: string; chip: string; label: string } {
  switch (source) {
    case "claude":
      return { border: "border-violet-400", chip: "bg-violet-100 text-violet-700", label: "Claude" };
    case "browser-use":
      return { border: "border-emerald-400", chip: "bg-emerald-100 text-emerald-700", label: "browser-use" };
    default:
      return { border: "border-slate-300", chip: "bg-slate-100 text-slate-600", label: "worker" };
  }
}

function groupByLane(steps: ScanStep[]): Map<string, ScanStep[]> {
  const out = new Map<string, ScanStep[]>();
  for (const s of steps) {
    const key = s.lane || "main";
    const bucket = out.get(key);
    if (bucket) bucket.push(s);
    else out.set(key, [s]);
  }
  return out;
}

// Render the agent's chain of reasoning as readable prose, not JSON.
// Prefers next_goal (forward-looking) → evaluation (reflection) → memory.
function reasoningText(step: ScanStep): string {
  const parts = [step.next_goal, step.evaluation, step.memory]
    .map((s) => (s || "").trim())
    .filter((s) => s.length > 0 && s.toLowerCase() !== "null");
  if (parts.length === 0) return `step ${step.step}`;
  // Dedupe identical adjacent fragments.
  const unique: string[] = [];
  for (const p of parts) {
    if (unique[unique.length - 1] !== p) unique.push(p);
  }
  return unique.join(" · ");
}

function Row({ step }: { step: ScanStep }) {
  const tone = sourceTone(step.source);
  return (
    <div className={`border-l-2 ${tone.border} pl-2 text-[11px] leading-snug`}>
      <div className="mb-0.5 flex items-center gap-1.5">
        <span
          className={`rounded px-1 py-0.5 text-[8px] font-semibold uppercase tracking-wide ${tone.chip}`}
        >
          {tone.label}
        </span>
        <span className="text-[9px] text-slate-400">step {step.step}</span>
      </div>
      <p className="whitespace-pre-line text-slate-700">{reasoningText(step)}</p>
    </div>
  );
}

function MiniPanel({
  lane,
  steps,
  compact = false,
}: {
  lane: string;
  steps: ScanStep[];
  compact?: boolean;
}) {
  // Show only the latest message per panel — the agent's current
  // chain-of-reasoning line. Keeps the layout stable and scannable.
  void compact;
  const recent = steps.slice(-MAX_ENTRIES_PER_PANEL);
  // Pick up any browser-use live-session URL from the first step that
  // carries one — lets the user pop open the live cloud browser window.
  const liveUrl = steps.find((s) => s.live_url)?.live_url || "";
  return (
    <div className="flex min-w-0 flex-col">
      <p className="mb-1 flex items-baseline gap-1.5 truncate text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        <span className="truncate">{lane}</span>
        <span className="text-slate-400 normal-case">({steps.length})</span>
        {liveUrl && (
          <a
            href={liveUrl}
            target="_blank"
            rel="noreferrer"
            className="ml-auto shrink-0 rounded-sm bg-emerald-100 px-1.5 py-0.5 text-[8px] font-semibold normal-case text-emerald-700 hover:bg-emerald-200"
            title="Open browser-use cloud live session"
          >
            ▶ watch live
          </a>
        )}
      </p>
      <div className="flex flex-col gap-1 rounded-md border border-slate-200 bg-slate-50/50 p-2">
        {recent.length === 0 ? (
          <p className="text-[10px] italic text-slate-400">waiting…</p>
        ) : (
          recent.map((s, i) => (
            <Row key={`${s.step}-${s.ts}-${i}`} step={s} />
          ))
        )}
      </div>
      {liveUrl && (
        <a
          href={liveUrl}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-flex items-center gap-1 self-start text-[10px] font-medium text-emerald-700 hover:text-emerald-900 hover:underline"
          title="Open browser-use cloud live session"
        >
          ▶ watch live on browser-use cloud
        </a>
      )}
    </div>
  );
}

export function ReasoningFeed({ steps }: { steps: ScanStep[] }) {
  if (!steps.length) return null;
  const grouped = groupByLane(steps);

  const targetSteps = grouped.get(TARGET_LANE) ?? [];
  const mergeSteps = grouped.get(MERGE_LANE) ?? [];
  // Only show the 4-agent row when at least one discovery agent has
  // actually emitted. This hides the "waiting…" placeholders when the
  // user is on Claude-fallback discovery (no parallel agents).
  const hasAnyDiscoveryAgentOutput = DISCOVERY_LANES.some(
    (l) => (grouped.get(l)?.length ?? 0) > 0,
  );
  const hasDiscoveryShape =
    targetSteps.length > 0 ||
    mergeSteps.length > 0 ||
    hasAnyDiscoveryAgentOutput;

  // Lanes that aren't part of the fixed discovery shape (e.g. claude /
  // cart walks) — rendered in a secondary grid below so they're still
  // visible once discovery completes. "main" (empty-lane) entries also
  // land here, relabeled for readability.
  const usedLanes = new Set<string>([
    TARGET_LANE,
    MERGE_LANE,
    ...DISCOVERY_LANES,
  ]);
  // Drop cart lanes that ended up being skipped / unscrapable — no
  // point showing a panel whose only story is "we gave up on this one".
  const isSkippedLane = (laneSteps: ScanStep[]): boolean =>
    laneSteps.some((s) => {
      const goal = (s.next_goal || "").toLowerCase();
      const evalText = (s.evaluation || "").toLowerCase();
      return (
        goal.startsWith("skipped ") ||
        evalText.startsWith("unsafe url") ||
        evalText.includes("not scrape-able") ||
        evalText.includes("not scrapeable")
      );
    });

  const extraLanes = Array.from(grouped.keys())
    .filter((l) => !usedLanes.has(l))
    .filter((l) => !isSkippedLane(grouped.get(l) ?? []))
    .sort((a, b) => {
      const r = (l: string) =>
        l === "main"
          ? 3
          : l.startsWith("claude:")
            ? 0
            : l.startsWith("cart:")
              ? 1
              : 2;
      return r(a) - r(b) || a.localeCompare(b);
    });

  // When the discovery shape hasn't been hit yet (scan jobs etc.),
  // fall back to the original single-panel layout.
  if (!hasDiscoveryShape) {
    return (
      <Card className="p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Agent reasoning
        </p>
        <div className="flex flex-col gap-1.5">
          {steps
            .slice(-8)
            .map((s, i) => (
              <Row key={`${s.step}-${s.ts}-${i}`} step={s} />
            ))}
        </div>
      </Card>
    );
  }

  return (
    <Card className="flex flex-col gap-3 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Agent reasoning
      </p>

      {/* TOP BAR — your store */}
      {targetSteps.length > 0 && (
        <MiniPanel lane={TARGET_LANE} steps={targetSteps} />
      )}

      {/* 4-AGENT ROW — fixed order, only when at least one agent fired */}
      {hasAnyDiscoveryAgentOutput && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {DISCOVERY_LANES.map((lane) => (
            <MiniPanel
              key={lane}
              lane={lane.replace("discover: ", "")}
              steps={grouped.get(lane) ?? []}
              compact
            />
          ))}
        </div>
      )}

      {/* BOTTOM BAR — merge */}
      {mergeSteps.length > 0 && (
        <MiniPanel lane={MERGE_LANE} steps={mergeSteps} />
      )}

      {/* Extras (claude + cart + pipeline) if they exist */}
      {extraLanes.length > 0 && (
        <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {extraLanes.map((lane) => (
            <MiniPanel
              key={lane}
              lane={lane === "main" ? "pipeline" : lane}
              steps={grouped.get(lane) ?? []}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
