// Mirrors backend models (CONTRACTS.md §2). Keep in sync with web/lib/types.ts.

export type Status = "pending" | "running" | "done" | "failed" | "cancelled";
export type Severity = "high" | "medium" | "low";
export type Category = "a11y" | "ux" | "contrast" | "nav";

export interface BoundingBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ScanFinding {
  id: string;
  scan_id: string;
  selector: string;
  xpath?: string | null;
  bounding_box?: BoundingBox | null;
  severity: Severity;
  category: Category;
  title: string;
  description: string;
  suggestion: string;
  page_url: string;
}

export interface ScanStep {
  step: number;
  ts: number;
  source?: string; // "worker" | "claude" | "browser-use"
  lane?: string; // panel id — empty string = main panel
  live_url?: string; // browser-use cloud live-session URL, if any
  evaluation: string;
  memory: string;
  next_goal: string;
  actions: string[];
}

export interface ScanStatus {
  scan_id: string;
  status: Status;
  progress: number;
  url: string;
  findings_count: number;
  report_id?: string | null;
  error?: string | null;
  steps?: ScanStep[];
}

export interface AnnotationsResponse {
  scan_id: string;
  url: string;
  annotations: ScanFinding[];
}

export interface ScanCreateResponse {
  scan_id: string;
  status: Status;
}

export interface CompetitorResult {
  id: string;
  job_id: string;
  name: string;
  url: string;
  price?: number | null;
  shipping?: number | null;
  tax?: number | null;
  discount?: string | null;
  checkout_total?: number | null;
  notes: string;
}

export interface CompetitorJobStatus {
  job_id: string;
  status: Status;
  progress: number;
  store_url: string;
  competitors: CompetitorResult[];
  report_id?: string | null;
  error?: string | null;
  steps?: ScanStep[];
}

// Fix operations — match backend FixOperation pydantic model.
export type FixOperation =
  | { kind: "css"; rules: string }
  | { kind: "attribute"; selector: string; name: string; value: string }
  | { kind: "class"; selector: string; classes: string }
  | { kind: "none"; reason: string };

export interface FixResponse {
  finding_id: string;
  operation: FixOperation;
}

// Message payloads
export type ExtensionMessage =
  | { type: "START_SCAN"; url: string }
  | { type: "SCAN_STATUS"; status: ScanStatus | null }
  | { type: "SIDEBAR_STATUS"; status: ScanStatus }
  | { type: "INJECT_ANNOTATIONS"; annotations: ScanFinding[] }
  | { type: "CLEAR_ANNOTATIONS" }
  | { type: "GET_STATE" }
  | { type: "PING" }
  | { type: "FIX_FINDING"; finding_id: string }
  | { type: "APPLY_FIX"; finding_id: string; operation: FixOperation }
  | { type: "FIX_ERROR"; finding_id: string; error: string };

export interface PopupState {
  scanId: string | null;
  status: ScanStatus | null;
  lastError: string | null;
}
