// Deterministic fee backfill + target-row synthesis used by both
// PriceDeltaChart and ExtraFeesChart so "our brand" lands alongside
// competitors in the stacked bars. Mirrors the backend estimate in
// `src/backend/workers/report_generator.py` so visuals stay consistent.

import type { CompetitorResult } from "./types";

export function seedOf(s: string): number {
  let n = 0;
  for (let i = 0; i < s.length; i++) n += s.charCodeAt(i);
  return n;
}

export interface FeeRow {
  name: string;
  price: number;
  shipping: number;
  tax: number;
  is_target?: boolean;
}

export function estimateShipping(sub: number, seed: number): number {
  if (sub >= 75) return 0;
  return Math.round((4.95 + (seed % 5)) * 100) / 100;
}

export function estimateTax(sub: number, seed: number): number {
  const rate = 0.07 + (seed % 3) / 100;
  return Math.round(sub * rate * 100) / 100;
}

export function backfillFees(c: CompetitorResult): FeeRow {
  const name = c.name || "?";
  const sub = (c.price ?? c.checkout_total ?? 0) as number;
  const seed = seedOf(name);
  const estimate = sub > 0 && seed % 2 === 0;
  let shipping = c.shipping ?? 0;
  let tax = c.tax ?? 0;
  if (estimate && (shipping == null || shipping <= 0)) {
    shipping = estimateShipping(sub, seed);
  }
  if (estimate && (tax == null || tax <= 0)) {
    tax = estimateTax(sub, seed);
  }
  return { name, price: c.price ?? 0, shipping, tax };
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

// Synthesize a target-row using the median competitor subtotal as the
// placeholder subtotal, then backfill shipping/tax deterministically
// keyed on store_url. Returns null when competitors lack any prices.
export function targetRow(
  storeUrl: string,
  competitors: CompetitorResult[],
): FeeRow | null {
  const subs = competitors
    .map((c) => (c.price ?? c.checkout_total) as number | null | undefined)
    .filter((v): v is number => typeof v === "number" && v > 0)
    .sort((a, b) => a - b);
  if (subs.length === 0) return null;
  const median = subs[Math.floor(subs.length / 2)];
  const seed = seedOf(storeUrl || "target");
  const shipping = estimateShipping(median, seed);
  const tax = estimateTax(median, seed);
  return {
    name: friendlyStoreName(storeUrl),
    price: median,
    shipping,
    tax,
    is_target: true,
  };
}
