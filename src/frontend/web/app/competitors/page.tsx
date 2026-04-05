import Link from "next/link";
import { CompetitorForm } from "@/components/CompetitorForm";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatUrl } from "@/lib/utils";

export const dynamic = "force-dynamic";

interface JobSummary {
  job_id: string;
  status: string;
  progress: number;
  store_url: string;
  report_id?: string | null;
  created_at: string;
  updated_at: string;
}

async function loadJobs(): Promise<JobSummary[]> {
  const base =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  try {
    const res = await fetch(`${base}/competitors?limit=25`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = (await res.json()) as { jobs?: JobSummary[] };
    return data.jobs ?? [];
  } catch {
    return [];
  }
}

export default async function CompetitorLanding() {
  const jobs = await loadJobs();

  return (
    <div className="flex flex-col gap-8">
      <section>
        <Badge variant="outline" className="mb-4">
          Competitor analysis
        </Badge>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">
          See what your competitors are charging.
        </h1>
        <p className="mt-3 max-w-2xl text-lg text-slate-600">
          We discover 3–5 comparable stores, extract prices, shipping, tax, and
          promo codes, and tell you exactly where your checkout falls behind.
        </p>
      </section>

      <Card className="max-w-3xl">
        <CardHeader>
          <CardTitle>Start a competitor analysis</CardTitle>
          <CardDescription>
            Give us your store URL and (optionally) a product hint.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CompetitorForm />
        </CardContent>
      </Card>

      {jobs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Previous runs ({jobs.length})</CardTitle>
            <CardDescription>
              Click a row to reopen its analysis.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-2 pr-4">Store</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((j) => {
                    const statusVariant =
                      j.status === "done"
                        ? "success"
                        : j.status === "failed" || j.status === "cancelled"
                          ? "high"
                          : "medium";
                    const started = j.created_at
                      ? new Date(j.created_at).toLocaleString()
                      : "—";
                    return (
                      <tr
                        key={j.job_id}
                        className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                      >
                        <td className="py-3 pr-4">
                          <Link
                            href={`/competitors/${j.job_id}`}
                            className="font-medium text-slate-900 hover:text-brand-600"
                          >
                            {formatUrl(j.store_url) || j.job_id}
                          </Link>
                        </td>
                        <td className="py-3 pr-4">
                          <Badge variant={statusVariant}>{j.status}</Badge>
                        </td>
                        <td className="py-3 text-slate-500">{started}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
