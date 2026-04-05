import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";
import { ShoppingBag } from "lucide-react";

export const metadata: Metadata = {
  title: "Storefront Reviewer",
  description:
    "Agentic accessibility, UX, and competitor analysis for any storefront.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
            <Link
              href="/"
              className="flex items-center gap-2 font-semibold text-slate-900"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-brand-600 text-white">
                <ShoppingBag className="h-4 w-4" />
              </span>
              Storefront Reviewer
            </Link>
            <nav className="flex items-center gap-6 text-sm">
              <Link
                href="/"
                className="text-slate-600 transition-colors hover:text-slate-900"
              >
                Scan
              </Link>
              <Link
                href="/competitors"
                className="text-slate-600 transition-colors hover:text-slate-900"
              >
                Competitors
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-10">{children}</main>
        <footer className="mt-16 border-t border-slate-200 bg-white">
          <div className="mx-auto max-w-6xl px-6 py-6 text-xs text-slate-500">
            Built for DiamondHacks 2026 · Storefront Reviewer
          </div>
        </footer>
      </body>
    </html>
  );
}
