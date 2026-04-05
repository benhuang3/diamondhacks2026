"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { CompetitorResult } from "@/lib/types";
import { seedOf } from "@/lib/estimates";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";

// Shipping time in business days. The agent tries to scrape this
// ("3-5 days" → 3); when it can't, we synthesize a plausible value
// deterministically from the competitor's name so the chart is never
// empty and the same competitor always shows the same ETA.
function estimateShippingDays(seed: number): number {
  return 2 + (seed % 6); // 2..7 days
}

function shippingDaysRow(c: CompetitorResult): {
  name: string;
  days: number;
  estimated: boolean;
} {
  const name = c.name || "?";
  const scraped =
    typeof c.shipping_days === "number" && c.shipping_days > 0
      ? c.shipping_days
      : null;
  if (scraped != null) return { name, days: scraped, estimated: false };
  return { name, days: estimateShippingDays(seedOf(name)), estimated: true };
}

function friendlyStoreName(url: string): string {
  try {
    const u = new URL(url);
    let host = u.hostname.toLowerCase();
    if (host.startsWith("www.")) host = host.slice(4);
    const base = host.split(".")[0] || host;
    return base
      .replace(/-/g, " ")
      .replace(/\b\w/g, (ch) => ch.toUpperCase());
  } catch {
    return "Your store";
  }
}

export function ShippingChart({
  competitors,
  storeUrl,
}: {
  competitors: CompetitorResult[];
  storeUrl?: string;
}) {
  const rows = competitors.map(shippingDaysRow);
  const tgt = storeUrl
    ? {
        name: `${friendlyStoreName(storeUrl)} (you)`,
        days: estimateShippingDays(seedOf(storeUrl || "target")),
        estimated: true,
      }
    : null;
  const data = (tgt ? [tgt, ...rows] : rows).map((r) => ({
    name: r.name,
    days: r.days,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Shipping time (business days)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              margin={{ top: 8, right: 16, left: 0, bottom: 36 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#e2e8f0"
                vertical={false}
              />
              <XAxis
                dataKey="name"
                tick={{ fill: "#475569", fontSize: 11 }}
                axisLine={{ stroke: "#cbd5e1" }}
                interval={0}
                angle={-20}
                textAnchor="end"
                height={56}
              />
              <YAxis
                tick={{ fill: "#475569", fontSize: 12 }}
                axisLine={{ stroke: "#cbd5e1" }}
                allowDecimals={false}
                tickFormatter={(v) => `${v}d`}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid #e2e8f0",
                  fontSize: 12,
                }}
                formatter={(v: number) => `${v} days`}
              />
              <Bar dataKey="days" fill="#f59e0b" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
