"use client";

import {
  ResponsiveContainer,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Tooltip,
} from "recharts";
import type { ScanFinding } from "@/lib/types";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";

export function FlowVisualization({
  findings,
}: {
  findings: ScanFinding[];
}) {
  const buckets: Record<string, { high: number; medium: number; low: number }> =
    {
      a11y: { high: 0, medium: 0, low: 0 },
      ux: { high: 0, medium: 0, low: 0 },
      contrast: { high: 0, medium: 0, low: 0 },
      nav: { high: 0, medium: 0, low: 0 },
    };
  for (const f of findings) {
    buckets[f.category][f.severity] += 1;
  }

  // weighted severity score per category — higher = more issues
  const data = Object.entries(buckets).map(([category, b]) => ({
    category,
    issues: b.high * 3 + b.medium * 2 + b.low * 1,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Flow & category breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={data} outerRadius="80%">
              <PolarGrid stroke="#e2e8f0" />
              <PolarAngleAxis
                dataKey="category"
                tick={{ fill: "#475569", fontSize: 12 }}
              />
              <PolarRadiusAxis
                tick={{ fill: "#94a3b8", fontSize: 10 }}
                angle={90}
              />
              <Radar
                name="Weighted issues"
                dataKey="issues"
                stroke="#4f46e5"
                fill="#4f46e5"
                fillOpacity={0.35}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid #e2e8f0",
                  fontSize: 12,
                }}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
