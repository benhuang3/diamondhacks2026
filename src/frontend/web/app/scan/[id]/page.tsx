"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  useScanPolling,
  getAnnotations,
  getReport,
} from "@/lib/api";
import type { ScanFinding, Report } from "@/lib/types";
import { FindingsList } from "@/components/FindingsList";
import { ScoreCard } from "@/components/ScoreCard";
import { FlowVisualization } from "@/components/FlowVisualization";
import { ScanLoader } from "@/components/ScanLoader";
import { ReasoningFeed } from "@/components/ReasoningFeed";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Download, ExternalLink } from "lucide-react";
import { formatUrl } from "@/lib/utils";
import {
  buildScanMarkdown,
  downloadMarkdown,
  scanMarkdownFilename,
} from "@/lib/markdown-export";

export default function ScanPage() {
  const params = useParams<{ id: string }>();
  const scanId = params.id;
  const { status } = useScanPolling(scanId);
  const [findings, setFindings] = React.useState<ScanFinding[]>([]);
  const [report, setReport] = React.useState<Report | null>(null);

  // Piggyback findings refresh on the scan-status poll: one loop, not two.
  // ``status.progress`` changes on every backend tick while the scan runs,
  // and once status reaches done/failed we fetch one last time.
  React.useEffect(() => {
    if (!scanId) return;
    let active = true;
    getAnnotations(scanId).then((r) => {
      if (active) setFindings(r.annotations);
    });
    return () => {
      active = false;
    };
  }, [scanId, status?.progress, status?.status]);

  React.useEffect(() => {
    if (status?.report_id) {
      getReport(status.report_id).then(setReport);
    }
  }, [status?.report_id]);

  const pct = Math.round((status?.progress ?? 0) * 100);
  const isRunning =
    status?.status === "pending" || status?.status === "running";

  const canDownload =
    !!status && !isRunning && (findings.length > 0 || !!report);
  const handleDownload = React.useCallback(() => {
    if (!status) return;
    const md = buildScanMarkdown(status, report, findings);
    downloadMarkdown(scanMarkdownFilename(status), md);
  }, [status, report, findings]);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back
        </Link>
        <div className="mt-3 flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              Scan report
            </h1>
            {status && (
              <Badge
                variant={
                  status.status === "done"
                    ? "success"
                    : status.status === "failed"
                      ? "high"
                      : "medium"
                }
              >
                {status.status}
              </Badge>
            )}
            {canDownload && (
              <button
                type="button"
                onClick={handleDownload}
                className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
                title="Download the scan report as a markdown file"
              >
                <Download className="h-3.5 w-3.5" />
                Download .md
              </button>
            )}
          </div>
          {status && (
            <a
              href={status.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex w-fit items-center gap-1 text-sm text-slate-500 hover:text-slate-900"
            >
              {formatUrl(status.url)}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </div>

      {isRunning && (
        <Card>
          <CardHeader>
            <CardTitle>Scanning in progress</CardTitle>
            <CardDescription>
              Crawling pages and analyzing DOM — polling every 3 seconds.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col items-center gap-5 py-6">
            <ScanLoader />
            <div className="flex w-full flex-col gap-2">
              <Progress value={pct} />
              <p className="text-center text-sm text-slate-500">
                {pct}% complete
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {status?.steps && status.steps.length > 0 && (
        <ReasoningFeed steps={status.steps} />
      )}

      {report && (
        <section className="flex flex-col gap-4">
          <h2 className="text-lg font-semibold text-slate-900">Scores</h2>
          <ScoreCard scores={report.scores} />
        </section>
      )}

      {report && (
        <Card>
          <CardHeader>
            <CardTitle>Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
              {report.summary}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-semibold text-slate-900">
              Findings ({findings.length})
            </h2>
            <FindingsList findings={findings} />
          </section>
        </div>
        <div className="flex flex-col gap-4">
          <FlowVisualization findings={findings} />
          {report && report.recommendations.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Recommendations</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-col gap-2 text-sm text-slate-700">
                  {report.recommendations.map((r, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="mt-0.5 text-brand-600">•</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
