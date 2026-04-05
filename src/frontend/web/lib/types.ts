// Mirrors CONTRACTS.md §2 pydantic models exactly.

export type Status = "pending" | "running" | "done" | "failed";
export type Severity = "high" | "medium" | "low";
export type Category = "a11y" | "ux" | "contrast" | "nav";
export type ReportKind = "scan" | "competitors";

export interface BoundingBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ScanRequest {
  url: string;
  max_pages?: number;
}

export interface ScanCreateResponse {
  scan_id: string;
  status: Status;
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

export interface CompetitorRequest {
  store_url: string;
  custom_prompt?: string;
  product_hint?: string;
}

export interface CompetitorCreateResponse {
  job_id: string;
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
}

export interface ReportSection {
  title: string;
  body: string;
  chart?: Record<string, unknown> | null;
}

export interface Report {
  report_id: string;
  kind: ReportKind;
  parent_id: string;
  scores: Record<string, number>;
  summary: string;
  sections: ReportSection[];
  recommendations: string[];
}
