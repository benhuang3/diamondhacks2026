"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { startScan } from "@/lib/api";
import { Loader2, Search } from "lucide-react";

export function ScanForm() {
  const router = useRouter();
  const [url, setUrl] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!url.trim()) {
      setError("Please enter a storefront URL.");
      return;
    }
    setLoading(true);
    try {
      const res = await startScan({ url: url.trim(), max_pages: 5 });
      router.push(`/scan/${res.scan_id}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            type="url"
            inputMode="url"
            placeholder="https://your-storefront.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="pl-9"
            disabled={loading}
          />
        </div>
        <Button type="submit" variant="gradient" disabled={loading} size="lg">
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Starting…
            </>
          ) : (
            "Start scan"
          )}
        </Button>
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}
    </form>
  );
}
