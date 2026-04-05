"use client";

import { useEffect, useRef, useState } from "react";
import type {
  ScanRequest,
  ScanCreateResponse,
  ScanStatus,
  ScanListResponse,
  AnnotationsResponse,
  CompetitorRequest,
  CompetitorCreateResponse,
  CompetitorJobStatus,
  Report,
} from "./types";
import {
  DEMO_SCAN_STATUS_1,
  DEMO_SCAN_STATUS_2,
  DEMO_SCAN_ID_1,
  DEMO_SCAN_ID_2,
  DEMO_COMPETITOR_JOB,
  DEMO_COMPETITOR_JOB_ID,
  DEMO_SCAN_REPORT,
  DEMO_COMPETITOR_REPORT,
  DEMO_SCAN_REPORT_ID,
  DEMO_COMP_REPORT_ID,
  DEMO_ANNOTATIONS_1,
} from "./demo-data";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

const FETCH_TIMEOUT_MS = 10_000;

async function safeFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers || {}),
      },
      cache: "no-store",
      signal: init?.signal ?? controller.signal,
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

// Fallback helpers pull from demo-data when either DEMO_MODE is true
// or the network request fails.

function demoScanStatus(id: string): ScanStatus {
  if (id === DEMO_SCAN_ID_2) return DEMO_SCAN_STATUS_2;
  return { ...DEMO_SCAN_STATUS_1, scan_id: id };
}

function demoCompetitorJob(id: string): CompetitorJobStatus {
  return { ...DEMO_COMPETITOR_JOB, job_id: id };
}

function demoReport(id: string): Report {
  if (id === DEMO_COMP_REPORT_ID) return DEMO_COMPETITOR_REPORT;
  if (id === DEMO_SCAN_REPORT_ID) return DEMO_SCAN_REPORT;
  return { ...DEMO_SCAN_REPORT, report_id: id };
}

export async function startScan(
  req: ScanRequest,
): Promise<ScanCreateResponse> {
  if (DEMO_MODE) {
    return { scan_id: DEMO_SCAN_ID_1, status: "pending" };
  }
  try {
    return await safeFetch<ScanCreateResponse>("/scan", {
      method: "POST",
      body: JSON.stringify(req),
    });
  } catch {
    return { scan_id: DEMO_SCAN_ID_1, status: "pending" };
  }
}

export async function getScan(scanId: string): Promise<ScanStatus> {
  if (DEMO_MODE) return demoScanStatus(scanId);
  try {
    return await safeFetch<ScanStatus>(`/scan/${scanId}`);
  } catch {
    return demoScanStatus(scanId);
  }
}

export async function listScans(limit = 50): Promise<ScanListResponse> {
  if (DEMO_MODE) return { scans: [] };
  try {
    return await safeFetch<ScanListResponse>(`/scans?limit=${limit}`);
  } catch {
    return { scans: [] };
  }
}

export async function getAnnotations(
  scanId: string,
): Promise<AnnotationsResponse> {
  if (DEMO_MODE) return { ...DEMO_ANNOTATIONS_1, scan_id: scanId };
  try {
    return await safeFetch<AnnotationsResponse>(`/annotations/${scanId}`);
  } catch {
    return { ...DEMO_ANNOTATIONS_1, scan_id: scanId };
  }
}

export async function startCompetitorJob(
  req: CompetitorRequest,
): Promise<CompetitorCreateResponse> {
  if (DEMO_MODE) {
    return { job_id: DEMO_COMPETITOR_JOB_ID, status: "pending" };
  }
  try {
    return await safeFetch<CompetitorCreateResponse>("/competitors", {
      method: "POST",
      body: JSON.stringify(req),
    });
  } catch {
    return { job_id: DEMO_COMPETITOR_JOB_ID, status: "pending" };
  }
}

export async function getCompetitorJob(
  jobId: string,
): Promise<CompetitorJobStatus> {
  if (DEMO_MODE) return demoCompetitorJob(jobId);
  try {
    return await safeFetch<CompetitorJobStatus>(`/competitors/${jobId}`);
  } catch {
    return demoCompetitorJob(jobId);
  }
}

export async function cancelCompetitorJob(
  jobId: string,
): Promise<CompetitorJobStatus | null> {
  if (DEMO_MODE) return null;
  try {
    return await safeFetch<CompetitorJobStatus>(
      `/competitors/${jobId}/cancel`,
      { method: "POST" },
    );
  } catch {
    return null;
  }
}

export async function getReport(reportId: string): Promise<Report> {
  if (DEMO_MODE) return demoReport(reportId);
  try {
    return await safeFetch<Report>(`/report/${reportId}`);
  } catch {
    return demoReport(reportId);
  }
}

// 3s polling hook for scans
export function useScanPolling(scanId: string | null) {
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(true);

  useEffect(() => {
    if (!scanId) return;
    active.current = true;

    const tick = async () => {
      try {
        const s = await getScan(scanId);
        if (!active.current) return;
        setStatus(s);
        if (s.status === "done" || s.status === "failed") return;
      } catch (e) {
        if (active.current) setError(String(e));
      }
      if (active.current) setTimeout(tick, 3000);
    };
    tick();

    return () => {
      active.current = false;
    };
  }, [scanId]);

  return { status, error };
}

// 3s polling hook for competitor jobs
export function useCompetitorPolling(jobId: string | null) {
  const [status, setStatus] = useState<CompetitorJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(true);

  useEffect(() => {
    if (!jobId) return;
    active.current = true;

    const tick = async () => {
      try {
        const s = await getCompetitorJob(jobId);
        if (!active.current) return;
        setStatus(s);
        if (s.status === "done" || s.status === "failed") return;
      } catch (e) {
        if (active.current) setError(String(e));
      }
      if (active.current) setTimeout(tick, 3000);
    };
    tick();

    return () => {
      active.current = false;
    };
  }, [jobId]);

  return { status, error };
}
