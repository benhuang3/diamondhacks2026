"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useCompetitorPolling, getReport } from "@/lib/api";
import type { Report } from "@/lib/types";
import { PriceDeltaChart } from "@/components/PriceDeltaChart";
import { PriceBreakdownChart } from "@/components/PriceBreakdownChart";
import { PriceMatrixTable } from "@/components/PriceMatrixTable";
import { ScoreCard } from "@/components/ScoreCard";
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
import { ArrowLeft, ExternalLink } from "lucide-react";
import { formatUrl } from "@/lib/utils";

export default function CompetitorReportPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const { status } = useCompetitorPolling(jobId);
  const [report, setReport] = React.useState<Report | null>(null);

  React.useEffect(() => {
    if (status?.report_id) {
      getReport(status.report_id).then(setReport);
    }
  }, [status?.report_id]);

  const pct = Math.round((status?.progress ?? 0) * 100);
  const isRunning =
    status?.status === "pending" || status?.status === "running";

  const competitors = status?.competitors ?? [];

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link
          href="/competitors"
          className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back
        </Link>
        <div className="mt-3 flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Competitor analysis
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
          <p className="mt-1 text-sm text-slate-500">
            Base store: {formatUrl(status.store_url)}
          </p>
        )}
      </div>

      {isRunning && (
        <Card>
          <CardHeader>
            <CardTitle>Discovering competitors</CardTitle>
            <CardDescription>
              Crawling comparable stores and extracting pricing.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Progress value={pct} />
            <p className="text-sm text-slate-500">{pct}% complete</p>
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

      {(() => {
        const matrix = report?.sections.find(
          (s) => s.title === "Price matrix",
        );
        const data = (matrix?.chart as
          | {
              data?: {
                product_names?: string[];
                rows?: {
                  competitor: string;
                  url: string;
                  prices: (number | null)[];
                }[];
              };
            }
          | undefined)?.data;
        if (!data?.product_names?.length || !data.rows?.length) return null;
        return (
          <PriceMatrixTable
            data={{
              product_names: data.product_names,
              rows: data.rows,
            }}
          />
        );
      })()}

      {(() => {
        const section = report?.sections.find(
          (s) => s.title === "Extra fees (shipping + tax)",
        );
        const data =
          (section?.chart as
            | {
                data?: {
                  label: string;
                  value: number;
                  shipping?: number;
                  tax?: number;
                }[];
              }
            | undefined)?.data ?? [];
        if (data.length === 0) return null;
        // Adapt the fees data to the existing PriceBreakdownChart shape.
        // Highest fee = "priced higher" (orange); lowest = emerald.
        const sorted = [...data].sort((a, b) => a.value - b.value);
        const median = sorted[Math.floor(sorted.length / 2)]?.value ?? 0;
        const adapted = data.map((d) => ({
          label: d.label,
          value: d.value,
          delta: d.value - median,
          is_target: false,
        }));
        return <PriceBreakdownChart data={adapted} body={section?.body} />;
      })()}

      {competitors.some((c) => c.checkout_total != null) && (
        <PriceDeltaChart competitors={competitors} />
      )}

      {competitors.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Competitors ({competitors.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-2 pr-4">Name</th>
                    <th className="py-2 pr-4">Price</th>
                    <th className="py-2 pr-4">Ship</th>
                    <th className="py-2 pr-4">Tax</th>
                    <th className="py-2 pr-4">Discount</th>
                    <th className="py-2 pr-4">Total</th>
                    <th className="py-2">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {competitors.map((c) => (
                    <tr
                      key={c.id}
                      className="border-b border-slate-100 last:border-0"
                    >
                      <td className="py-3 pr-4">
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 font-medium text-slate-900 hover:text-brand-600"
                        >
                          {c.name}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      </td>
                      <td className="py-3 pr-4 tabular-nums text-slate-700">
                        {c.price != null ? `$${c.price.toFixed(2)}` : "—"}
                      </td>
                      <td className="py-3 pr-4 tabular-nums text-slate-700">
                        {c.shipping != null
                          ? `$${c.shipping.toFixed(2)}`
                          : "—"}
                      </td>
                      <td className="py-3 pr-4 tabular-nums text-slate-700">
                        {c.tax != null ? `$${c.tax.toFixed(2)}` : "—"}
                      </td>
                      <td className="py-3 pr-4">
                        {c.discount ? (
                          <Badge variant="success">{c.discount}</Badge>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-4 font-semibold tabular-nums text-slate-900">
                        {c.checkout_total != null
                          ? `$${c.checkout_total.toFixed(2)}`
                          : "—"}
                      </td>
                      <td className="py-3 text-slate-600">{c.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {report && (
        <div className="grid gap-4 lg:grid-cols-2">
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
        </div>
      )}
    </div>
  );
}
