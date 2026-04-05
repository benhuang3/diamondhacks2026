"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "./ui/card";

interface Row {
  label: string;
  value: number;
  delta?: number | null;
  is_target?: boolean;
}

export function PriceBreakdownChart({
  data,
  body,
}: {
  data: Row[];
  body?: string;
}) {
  if (!data.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Price breakdown by product</CardTitle>
        <CardDescription>
          Featured product price for each competitor vs. your store.
          Competitors are ordered by the largest absolute gap first.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {body && (
          <div className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
            {body}
          </div>
        )}
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 8, right: 48, left: 8, bottom: 8 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#e2e8f0"
                horizontal={false}
              />
              <XAxis
                type="number"
                tick={{ fill: "#475569", fontSize: 12 }}
                axisLine={{ stroke: "#cbd5e1" }}
                tickFormatter={(v) => `$${v}`}
              />
              <YAxis
                type="category"
                dataKey="label"
                tick={{ fill: "#475569", fontSize: 11 }}
                axisLine={{ stroke: "#cbd5e1" }}
                width={220}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid #e2e8f0",
                  fontSize: 12,
                }}
                formatter={(v: number, _name, item) => {
                  const row = item?.payload as Row | undefined;
                  const delta = row?.delta;
                  const deltaStr =
                    delta == null
                      ? ""
                      : ` (${delta > 0 ? "+" : ""}$${delta.toFixed(2)} vs. you)`;
                  return [`$${v.toFixed(2)}${deltaStr}`, "price"];
                }}
              />
              <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                {data.map((row, i) => (
                  <Cell
                    key={i}
                    fill={
                      row.is_target
                        ? "#4f46e5"
                        : (row.delta ?? 0) > 0
                          ? "#f97316"
                          : "#10b981"
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="flex items-center gap-4 text-xs text-slate-500">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-brand-600" /> your store
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-orange-500" /> priced
            higher
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" /> priced
            lower
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
