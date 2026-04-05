// Render a scan's report + findings as a downloadable markdown document.
// Used by the scans tab's "Download .md" button — keeps all report text
// local to the client, no extra backend endpoint needed.

import type { Report, ScanFinding, ScanStatus, Severity } from "@/lib/types";

const SEVERITY_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2 };

function scoreLine(scores: Record<string, number>): string {
  const keys = Object.keys(scores);
  if (keys.length === 0) return "";
  return keys
    .map((k) => `- **${k}**: ${Math.round(scores[k])}/100`)
    .join("\n");
}

function findingsSection(findings: ScanFinding[]): string {
  if (findings.length === 0) return "_No findings recorded._";
  const sorted = [...findings].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
  );
  return sorted
    .map((f, i) => {
      const lines = [
        `### ${i + 1}. ${f.title}`,
        `**Severity:** ${f.severity} · **Category:** ${f.category}`,
        f.page_url ? `**Page:** ${f.page_url}` : "",
        f.selector ? `**Selector:** \`${f.selector}\`` : "",
        "",
        f.description,
        "",
        f.suggestion ? `> **Fix:** ${f.suggestion}` : "",
      ];
      return lines.filter(Boolean).join("\n");
    })
    .join("\n\n---\n\n");
}

export function buildScanMarkdown(
  status: ScanStatus,
  report: Report | null,
  findings: ScanFinding[],
): string {
  const generatedAt = new Date().toISOString();
  const parts: string[] = [];
  parts.push(`# Storefront scan report`);
  parts.push("");
  parts.push(`- **URL:** ${status.url}`);
  parts.push(`- **Status:** ${status.status}`);
  parts.push(`- **Findings:** ${findings.length}`);
  parts.push(`- **Generated:** ${generatedAt}`);
  parts.push("");

  if (report) {
    const line = scoreLine(report.scores);
    if (line) {
      parts.push(`## Scores`);
      parts.push("");
      parts.push(line);
      parts.push("");
    }
    if (report.summary) {
      parts.push(`## Summary`);
      parts.push("");
      parts.push(report.summary.trim());
      parts.push("");
    }
    for (const section of report.sections ?? []) {
      if (!section.title && !section.body) continue;
      parts.push(`## ${section.title || "Section"}`);
      parts.push("");
      parts.push((section.body || "").trim());
      parts.push("");
    }
    if (report.recommendations.length > 0) {
      parts.push(`## Recommendations`);
      parts.push("");
      for (const r of report.recommendations) parts.push(`- ${r}`);
      parts.push("");
    }
  }

  parts.push(`## Findings (${findings.length})`);
  parts.push("");
  parts.push(findingsSection(findings));
  parts.push("");

  return parts.join("\n");
}

export function downloadMarkdown(filename: string, markdown: string): void {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function scanMarkdownFilename(status: ScanStatus): string {
  let host = "scan";
  try {
    host = new URL(status.url).hostname.replace(/[^a-z0-9.-]/gi, "_");
  } catch {
    /* keep fallback */
  }
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  return `${host}-${ts}.md`;
}
