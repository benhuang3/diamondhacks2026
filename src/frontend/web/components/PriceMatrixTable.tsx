"use client";

import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "./ui/card";

interface MatrixRow {
  competitor: string;
  url: string;
  prices: (number | null)[];
}

interface MatrixData {
  product_names: string[];
  rows: MatrixRow[];
}

export function PriceMatrixTable({ data }: { data: MatrixData }) {
  if (!data.product_names?.length || !data.rows?.length) return null;

  const priceClass = (col: number, v: number | null): string => {
    if (v == null) return "text-slate-400";
    const colPrices = data.rows
      .map((r) => r.prices[col])
      .filter((p): p is number => typeof p === "number");
    if (colPrices.length < 2) return "text-slate-900";
    const min = Math.min(...colPrices);
    const max = Math.max(...colPrices);
    if (v === min && min !== max) return "text-emerald-700 font-semibold";
    if (v === max && min !== max) return "text-rose-700 font-semibold";
    return "text-slate-900";
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Price matrix — top 3 shared products × competitors</CardTitle>
        <CardDescription>
          Each cell is the price observed on that competitor&rsquo;s site.
          Column minimum shown in green, maximum in red. &ldquo;—&rdquo; =
          not spotted during the cart walk.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="py-2 pr-4">Competitor</th>
                {data.product_names.map((n, i) => (
                  <th key={i} className="py-2 pr-4">
                    {n}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr
                  key={i}
                  className="border-b border-slate-100 last:border-0"
                >
                  <td className="py-3 pr-4">
                    {r.url ? (
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-slate-900 hover:text-brand-600"
                      >
                        {r.competitor}
                      </a>
                    ) : (
                      <span className="font-medium text-slate-900">
                        {r.competitor}
                      </span>
                    )}
                  </td>
                  {r.prices.map((p, j) => (
                    <td
                      key={j}
                      className={`py-3 pr-4 tabular-nums ${priceClass(j, p)}`}
                    >
                      {p != null ? `$${p.toFixed(2)}` : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
