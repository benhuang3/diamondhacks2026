import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function severityColor(severity: "high" | "medium" | "low") {
  switch (severity) {
    case "high":
      return "bg-rose-100 text-rose-800 border-rose-200";
    case "medium":
      return "bg-amber-100 text-amber-800 border-amber-200";
    case "low":
      return "bg-sky-100 text-sky-800 border-sky-200";
  }
}

export function scoreColor(score: number) {
  if (score >= 80) return "text-emerald-600";
  if (score >= 60) return "text-amber-600";
  return "text-rose-600";
}

export function formatUrl(u: string) {
  try {
    const url = new URL(u);
    return url.host + (url.pathname === "/" ? "" : url.pathname);
  } catch {
    return u;
  }
}
