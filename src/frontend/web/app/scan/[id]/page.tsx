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
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { formatUrl } from "@/lib/utils";

export default function ScanPage() {
  const params = useParams<{ id: string }>();
  const scanId = params.id;
  const { status } = useScanPolling(scanId);
  const [findings, setFindings] = React.useState<ScanFinding[]>([]);
  const [report, setReport] = React.useState<Report | null>(null);

  React.useEffect(() => {
    if (!scanId) return;
    getAnnotations(scanId).then((r) => setFindings(r.annotations));
  }, [scanId]);

  React.useEffect(() => {
    if (status?.report_id) {
      getReport(status.report_id).then(setReport);
    }
  }, [status?.report_id]);

  const pct = Math.round((status?.progress ?? 0) * 100);
  const isRunning =
    status?.status === "pending" || status?.status === "running";

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
          <div className="flex items-center gap-2">
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
          <CardContent className="flex flex-col gap-3">
            <Progress value={pct} />
            <p className="text-sm text-slate-500">{pct}% complete</p>
          </CardContent>
        </Card>
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
