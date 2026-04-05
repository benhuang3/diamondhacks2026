"use client";

import * as React from "react";
import type { ScanFinding } from "@/lib/types";
import { Badge } from "./ui/badge";
import { Card } from "./ui/card";
import { AlertTriangle, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export function FindingsList({ findings }: { findings: ScanFinding[] }) {
  if (!findings.length) {
    return (
      <Card className="flex items-center gap-3 p-6">
        <AlertTriangle className="h-5 w-5 text-slate-400" />
        <p className="text-sm text-slate-500">
          No findings yet. Scan is still running or no issues were detected.
        </p>
      </Card>
    );
  }

  // sort by severity: high -> medium -> low
  const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
  const sorted = [...findings].sort(
    (a, b) => order[a.severity] - order[b.severity],
  );

  return (
    <div className="flex flex-col gap-3">
      {sorted.map((f) => (
        <FindingRow key={f.id} finding={f} />
      ))}
    </div>
  );
}

function FindingRow({ finding }: { finding: ScanFinding }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Card className="overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 p-4 text-left transition-colors hover:bg-slate-50"
      >
        <Badge variant={finding.severity}>{finding.severity}</Badge>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h4 className="font-medium text-slate-900">{finding.title}</h4>
            <Badge variant="outline" className="text-xs">
              {finding.category}
            </Badge>
          </div>
          <p className="mt-1 line-clamp-1 font-mono text-xs text-slate-500">
            {finding.selector}
          </p>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-slate-400 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div className="border-t border-slate-100 bg-slate-50/50 p-4 text-sm">
          <div className="mb-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Description
            </p>
            <p className="text-slate-700">{finding.description}</p>
          </div>
          <div className="mb-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Suggested fix
            </p>
            <p className="text-slate-700">{finding.suggestion}</p>
          </div>
          {finding.xpath && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                XPath
              </p>
              <p className="break-all font-mono text-xs text-slate-600">
                {finding.xpath}
              </p>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
