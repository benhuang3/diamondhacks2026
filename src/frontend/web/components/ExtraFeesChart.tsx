"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import type { CompetitorResult } from "@/lib/types";
import { backfillFees, targetRow } from "@/lib/estimates";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";

export function ExtraFeesChart({
  competitors,
  storeUrl,
}: {
  competitors: CompetitorResult[];
  storeUrl?: string;
}) {
  const rows = competitors.map(backfillFees);
  const tgt = storeUrl ? targetRow(storeUrl, competitors) : null;
  const data = (tgt ? [tgt, ...rows] : rows).map((r) => ({
    name: r.is_target ? `${r.name} (you)` : r.name,
    shipping: r.shipping,
    tax: r.tax,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Extra fees (shipping + tax)</CardTitle>
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
                tickFormatter={(v) => `$${v}`}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid #e2e8f0",
                  fontSize: 12,
                }}
                formatter={(v: number) => `$${v.toFixed(2)}`}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar
                dataKey="shipping"
                stackId="fees"
                fill="#f59e0b"
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="tax"
                stackId="fees"
                fill="#0ea5e9"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
