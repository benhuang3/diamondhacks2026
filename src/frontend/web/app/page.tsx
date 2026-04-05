import Link from "next/link";
import { ScanForm } from "@/components/ScanForm";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DEMO_RECENT_SCANS } from "@/lib/demo-data";
import { formatUrl } from "@/lib/utils";
import { ArrowRight, Activity, Eye, Zap } from "lucide-react";

export default function LandingPage() {
  return (
    <div className="flex flex-col gap-10">
      <section className="relative flex flex-col gap-6">
        <div className="hero-blobs" aria-hidden="true" />
        <div className="relative z-10 max-w-2xl">
          <Badge variant="outline" className="mb-4">
            Agentic storefront review
          </Badge>
          <h1 className="text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
            Audit any storefront in under a minute.
          </h1>
          <p className="mt-4 text-lg text-slate-600">
            Paste a URL. We crawl the site with a browser agent, spot
            accessibility and UX issues with Claude, and return prioritized,
            selector-linked fixes you can hand to a designer or ship straight
            to production.
          </p>
        </div>
        <Card className="relative z-10 max-w-3xl">
          <CardHeader>
            <CardTitle>Start a new scan</CardTitle>
            <CardDescription>
              We&rsquo;ll crawl up to 5 pages and report back in ~60 seconds.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ScanForm />
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        <FeatureCard
          icon={<Eye className="h-5 w-5" />}
          title="Accessibility audit"
          body="WCAG-aligned findings with contrast, focus, alt-text, and labeling checks."
        />
        <FeatureCard
          icon={<Activity className="h-5 w-5" />}
          title="UX & flow review"
          body="Navigation, checkout funnel, and cart experience — assessed like a real shopper."
        />
        <FeatureCard
          icon={<Zap className="h-5 w-5" />}
          title="Selector-ready fixes"
          body="Every finding ships with CSS selectors, xpath, and a concrete patch suggestion."
        />
      </section>

      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Recent scans</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {DEMO_RECENT_SCANS.map((s) => (
            <Link
              key={s.scan_id}
              href={`/scan/${s.scan_id}`}
              className="group"
            >
              <Card className="p-4 transition-shadow hover:shadow-md">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-slate-900">
                      {formatUrl(s.url)}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {s.findings_count} findings
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={s.status} />
                    <ArrowRight className="h-4 w-4 text-slate-400 transition-transform group-hover:translate-x-0.5" />
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <Card className="p-5">
      <div className="flex h-9 w-9 items-center justify-center rounded-md bg-brand-50 text-brand-600">
        {icon}
      </div>
      <h3 className="mt-3 font-semibold text-slate-900">{title}</h3>
      <p className="mt-1 text-sm text-slate-600">{body}</p>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variant: "success" | "high" | "medium" | "default" =
    status === "done"
      ? "success"
      : status === "failed"
        ? "high"
        : status === "running"
          ? "medium"
          : "default";
  return <Badge variant={variant}>{status}</Badge>;
}
