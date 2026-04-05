import { Card } from "./ui/card";
import { cn, scoreColor } from "@/lib/utils";

export function ScoreCard({ scores }: { scores: Record<string, number> }) {
  const entries = Object.entries(scores);
  return (
    <div
      className={cn(
        "grid gap-4",
        entries.length === 3 ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-2",
      )}
    >
      {entries.map(([k, v]) => (
        <Card
          key={k}
          className="flex flex-col items-start gap-2 p-5"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {k}
          </p>
          <div className="flex items-baseline gap-1">
            <span className={cn("text-4xl font-semibold", scoreColor(v))}>
              {v}
            </span>
            <span className="text-sm text-slate-400">/ 100</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={cn(
                "h-full rounded-full",
                v >= 80
                  ? "bg-emerald-500"
                  : v >= 60
                    ? "bg-amber-500"
                    : "bg-rose-500",
              )}
              style={{ width: `${v}%` }}
            />
          </div>
        </Card>
      ))}
    </div>
  );
}
