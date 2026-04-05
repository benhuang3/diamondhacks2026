"use client";

import * as React from "react";
import Link from "next/link";
import { listScans } from "@/lib/api";
import type { ScanSummary } from "@/lib/types";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { ArrowRight, RefreshCw } from "lucide-react";
import { formatUrl } from "@/lib/utils";

const POLL_MS = 5000;

function statusVariant(
  s: ScanSummary["status"],
): "success" | "high" | "medium" | "default" {
  if (s === "done") return "success";
  if (s === "failed") return "high";
  if (s === "running") return "medium";
  return "default";
}

function relTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Math.max(0, Date.now() - t);
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function ScansPage() {
  const [scans, setScans] = React.useState<ScanSummary[] | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const load = React.useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await listScans(100);
      setScans(res.scans);
    } finally {
      setRefreshing(false);
    }
  }, []);

  React.useEffect(() => {
    let active = true;
    load();
    const tick = () => {
      if (!active) return;
      load().finally(() => {
        if (active) setTimeout(tick, POLL_MS);
      });
    };
    const t = setTimeout(tick, POLL_MS);
    return () => {
      active = false;
      clearTimeout(t);
    };
  }, [load]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Scans
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Every scan started from the web UI or the Chrome extension shows
            up here. Auto-refreshes every {POLL_MS / 1000}s.
          </p>
        </div>
        <button
          onClick={load}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      {scans === null ? (
        <Card className="p-6">
          <p className="text-sm text-slate-500">Loading…</p>
        </Card>
      ) : scans.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No scans yet</CardTitle>
            <CardDescription>
              Start one from the <Link className="underline" href="/">Scan</Link>{" "}
              tab, or use the Chrome extension on any storefront.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {scans.map((s) => (
            <Link key={s.scan_id} href={`/scan/${s.scan_id}`} className="group">
              <Card className="finding-glow p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Badge variant={statusVariant(s.status)}>
                        {s.status}
                      </Badge>
                      <p className="truncate font-medium text-slate-900">
                        {formatUrl(s.url)}
                      </p>
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
                      <span>
                        {s.findings_count} finding
                        {s.findings_count === 1 ? "" : "s"}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>{relTime(s.created_at)}</span>
                    </div>
                    {(s.status === "pending" || s.status === "running") && (
                      <div className="mt-2">
                        <Progress value={Math.round(s.progress * 100)} />
                      </div>
                    )}
                  </div>
                  <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-slate-400 transition-transform group-hover:translate-x-0.5" />
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
