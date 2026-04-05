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
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";

export function PriceDeltaChart({
  competitors,
}: {
  competitors: CompetitorResult[];
}) {
  const data = competitors.map((c) => ({
    name: c.name,
    price: c.price ?? 0,
    shipping: c.shipping ?? 0,
    tax: c.tax ?? 0,
    total: c.checkout_total ?? 0,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Checkout cost breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#e2e8f0"
                vertical={false}
              />
              <XAxis
                dataKey="name"
                tick={{ fill: "#475569", fontSize: 12 }}
                axisLine={{ stroke: "#cbd5e1" }}
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
                dataKey="price"
                stackId="cost"
                fill="#4f46e5"
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="shipping"
                stackId="cost"
                fill="#f59e0b"
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="tax"
                stackId="cost"
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
