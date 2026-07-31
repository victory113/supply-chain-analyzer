/**
 * Types mirroring the backend's Pydantic schemas.
 *
 * Hand-written rather than generated so the diff is reviewable, but they track
 * `app/schemas/*.py` field for field — if the API changes, this file is the
 * single place the frontend needs to follow.
 */

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export type UploadStatus =
  | 'pending'
  | 'parsing'
  | 'analyzing'
  | 'completed'
  | 'failed';

export type AnalysisStatus = 'queued' | 'running' | 'completed' | 'failed';

export type ShipmentStatus =
  | 'on_time'
  | 'delayed'
  | 'critical'
  | 'delivered'
  | 'cancelled'
  | 'unknown';

export type TrendDirection =
  | 'improving'
  | 'worsening'
  | 'stable'
  | 'insufficient_data';

/** Terminal states — nothing further will change, so polling can stop. */
export const TERMINAL_ANALYSIS_STATUSES: readonly AnalysisStatus[] = [
  'completed',
  'failed',
];

// ── Auth ──────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  organization: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Token {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface RegisterPayload {
  email: string;
  password: string;
  full_name?: string | null;
  organization?: string | null;
}

export interface LoginPayload {
  email: string;
  password: string;
}

// ── Uploads ───────────────────────────────────────────────────────────

export interface Upload {
  id: string;
  filename: string;
  label: string | null;
  size_bytes: number;
  row_count: number;
  rejected_row_count: number;
  status: UploadStatus;
  error_message: string | null;
  created_at: string;
}

export interface UploadAccepted {
  upload: Upload;
  analysis_id: string;
  task_id: string | null;
  poll_url: string;
}

export interface Shipment {
  id: string;
  shipment_ref: string | null;
  vendor: string | null;
  product: string | null;
  origin_country: string | null;
  destination: string | null;
  quantity: number | null;
  unit_cost: number | null;
  lead_time_days: number | null;
  delay_days: number;
  status: ShipmentStatus;
  shipped_on: string | null;
  last_updated: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ── Analytics (all computed in Python, never by the model) ────────────

export interface KpiSummary {
  total_shipments: number;
  late_shipments: number;
  late_shipment_pct: number;
  avg_delay_days: number;
  avg_delay_days_when_late: number;
  median_delay_days: number;
  p90_delay_days: number;
  avg_lead_time_days: number;
  delivery_success_rate: number;
  total_value: number;
  value_at_risk: number;
  distinct_vendors: number;
  distinct_countries: number;
}

export interface VendorScore {
  vendor: string;
  shipment_count: number;
  late_count: number;
  late_pct: number;
  avg_delay_days: number;
  avg_lead_time_days: number;
  total_value: number;
  value_at_risk: number;
  health_score: number;
  risk_level: RiskLevel;
}

export interface CountryRisk {
  country: string;
  shipment_count: number;
  late_count: number;
  late_pct: number;
  avg_delay_days: number;
  total_value: number;
  risk_score: number;
  risk_level: RiskLevel;
}

export interface TrendPoint {
  period: string;
  shipment_count: number;
  late_count: number;
  late_pct: number;
  avg_delay_days: number;
  total_value: number;
}

export interface TrendAnalysis {
  points: TrendPoint[];
  direction: TrendDirection;
  delay_change_pct: number | null;
  commentary: string;
}

export interface RiskBreakdown {
  score: number;
  level: RiskLevel;
  components: Record<string, number>;
  weights: Record<string, number>;
}

export interface AnalyticsReport {
  upload_id: string;
  kpis: KpiSummary;
  vendors: VendorScore[];
  countries: CountryRisk[];
  trend: TrendAnalysis;
  risk: RiskBreakdown;
  healthy_signals: string[];
}

export interface HistoricalPoint {
  upload_id: string;
  label: string | null;
  uploaded_at: string;
  row_count: number;
  late_shipment_pct: number;
  avg_delay_days: number;
  delivery_success_rate: number;
  risk_score: number;
}

export interface HistoricalReport {
  points: HistoricalPoint[];
  direction: TrendDirection;
  summary: string;
}

// ── AI analysis ───────────────────────────────────────────────────────

export interface Risk {
  id: string;
  position: number;
  title: string;
  risk_level: RiskLevel;
  explanation: string | null;
  recommendation: string | null;
  affected_items: string[] | null;
  /** The computed metric field this risk is grounded in. */
  evidence_metric: string | null;
}

export interface Analysis {
  id: string;
  upload_id: string;
  status: AnalysisStatus;
  summary: string | null;
  overall_risk: RiskLevel | null;
  risk_score: number | null;
  healthy_signals: string[] | null;
  model_name: string | null;
  duration_ms: number | null;
  error_message: string | null;
  created_at: string;
  risks: Risk[];
}

export interface AnalysisDetail extends Analysis {
  metrics_snapshot: AnalyticsReport | null;
}

export interface AnalysisStatusRead {
  id: string;
  status: AnalysisStatus;
  error_message: string | null;
}

export interface ComparisonChange {
  title: string;
  change_type: 'IMPROVED' | 'WORSENED' | 'NEW_ISSUE';
  explanation: string;
  recommendation: string;
  affected_items: string[];
}

export interface ComparisonResult {
  net_change: string;
  summary: string;
  changes: ComparisonChange[];
  before: AnalyticsReport;
  after: AnalyticsReport;
}

// ── Chat ──────────────────────────────────────────────────────────────

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatSource {
  kind: string;
  reference: string;
  detail: string;
}

export interface ChatRequest {
  question: string;
  upload_id?: string | null;
  history?: ChatTurn[];
}

export interface ChatResponse {
  answer: string;
  sources: ChatSource[];
  uploads_considered: number;
}

// ── Errors ────────────────────────────────────────────────────────────

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}
