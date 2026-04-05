"use client";

import * as React from "react";
import type { ScanFinding } from "@/lib/types";
import { Badge } from "./ui/badge";
import { Card } from "./ui/card";
import { AlertTriangle, ChevronDown, FileText } from "lucide-react";
import { cn, formatUrl } from "@/lib/utils";

const SEVERITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

function groupByPage(
  findings: ScanFinding[],
): { page_url: string; findings: ScanFinding[] }[] {
  const map = new Map<string, ScanFinding[]>();
  for (const f of findings) {
    const key = f.page_url || "(unknown page)";
    let bucket = map.get(key);
    if (!bucket) {
      bucket = [];
      map.set(key, bucket);
    }
    bucket.push(f);
  }
  // sort findings inside each group by severity
  const groups = Array.from(map.entries()).map(([page_url, items]) => ({
    page_url,
    findings: items
      .slice()
      .sort(
        (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
      ),
  }));
  // order pages by descending high-severity count, then total count
  groups.sort((a, b) => {
    const ah = a.findings.filter((f) => f.severity === "high").length;
    const bh = b.findings.filter((f) => f.severity === "high").length;
    if (ah !== bh) return bh - ah;
    return b.findings.length - a.findings.length;
  });
  return groups;
}

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

  const groups = groupByPage(findings);

  return (
    <div className="flex flex-col gap-4">
      {groups.map((g) => (
        <PageGroup
          key={g.page_url}
          pageUrl={g.page_url}
          findings={g.findings}
        />
      ))}
    </div>
  );
}

function severityCounts(findings: ScanFinding[]) {
  const c = { high: 0, medium: 0, low: 0 };
  for (const f of findings) c[f.severity] = (c[f.severity] ?? 0) + 1;
  return c;
}

function PageGroup({
  pageUrl,
  findings,
}: {
  pageUrl: string;
  findings: ScanFinding[];
}) {
  const [open, setOpen] = React.useState(true);
  const counts = severityCounts(findings);
  return (
    <section className="flex flex-col gap-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="group flex items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-slate-100/60"
      >
        <FileText className="h-4 w-4 shrink-0 text-slate-500" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900">
            {formatUrl(pageUrl)}
          </p>
        </div>
        <div className="flex items-center gap-1.5 text-xs">
          {counts.high > 0 && <Badge variant="high">{counts.high} high</Badge>}
          {counts.medium > 0 && (
            <Badge variant="medium">{counts.medium} med</Badge>
          )}
          {counts.low > 0 && <Badge variant="low">{counts.low} low</Badge>}
          <span className="ml-1 text-slate-400">({findings.length})</span>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-slate-400 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div className="flex flex-col gap-3 pl-6">
          {findings.map((f) => (
            <FindingRow key={f.id} finding={f} />
          ))}
        </div>
      )}
    </section>
  );
}

function FindingRow({ finding }: { finding: ScanFinding }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Card className="finding-glow overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 p-4 text-left transition-colors hover:bg-slate-50/60"
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
