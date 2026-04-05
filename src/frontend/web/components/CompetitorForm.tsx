"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { startCompetitorJob } from "@/lib/api";
import { Loader2, TrendingUp } from "lucide-react";

export function CompetitorForm() {
  const router = useRouter();
  const [storeUrl, setStoreUrl] = React.useState("");
  const [productHint, setProductHint] = React.useState("");
  const [customPrompt, setCustomPrompt] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!storeUrl.trim()) {
      setError("Please enter your store URL.");
      return;
    }
    setLoading(true);
    try {
      const res = await startCompetitorJob({
        store_url: storeUrl.trim(),
        product_hint: productHint.trim() || undefined,
        custom_prompt: customPrompt.trim() || undefined,
      });
      router.push(`/competitors/${res.job_id}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <label className="text-sm font-medium text-slate-700">Store URL</label>
        <div className="relative">
          <TrendingUp className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            type="url"
            placeholder="https://your-store.com"
            value={storeUrl}
            onChange={(e) => setStoreUrl(e.target.value)}
            className="pl-9"
            disabled={loading}
          />
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <label className="text-sm font-medium text-slate-700">
          Product hint{" "}
          <span className="text-slate-400">(optional)</span>
        </label>
        <Input
          placeholder="e.g. trail running shoes"
          value={productHint}
          onChange={(e) => setProductHint(e.target.value)}
          disabled={loading}
        />
      </div>
      <div className="flex flex-col gap-2">
        <label className="text-sm font-medium text-slate-700">
          Custom prompt <span className="text-slate-400">(optional)</span>
        </label>
        <Input
          placeholder="Focus on shipping fees and discount codes"
          value={customPrompt}
          onChange={(e) => setCustomPrompt(e.target.value)}
          disabled={loading}
        />
      </div>
      <Button type="submit" variant="gradient" disabled={loading} size="lg">
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" /> Finding competitors…
          </>
        ) : (
          "Analyze competitors"
        )}
      </Button>
      {error && <p className="text-sm text-rose-600">{error}</p>}
    </form>
  );
}
