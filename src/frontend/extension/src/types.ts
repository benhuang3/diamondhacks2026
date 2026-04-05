// Mirrors backend models (CONTRACTS.md §2). Keep in sync with web/lib/types.ts.

export type Status = "pending" | "running" | "done" | "failed";
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

export interface ScanStatus {
  scan_id: string;
  status: Status;
  progress: number;
  url: string;
  findings_count: number;
  report_id?: string | null;
  error?: string | null;
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

// Message payloads
export type ExtensionMessage =
  | { type: "START_SCAN"; url: string }
  | { type: "SCAN_STATUS"; status: ScanStatus | null }
  | { type: "INJECT_ANNOTATIONS"; annotations: ScanFinding[] }
  | { type: "CLEAR_ANNOTATIONS" }
  | { type: "GET_STATE" };

export interface PopupState {
  scanId: string | null;
  status: ScanStatus | null;
  lastError: string | null;
}
