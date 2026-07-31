/** Typed wrappers for every backend route the UI uses. */

import { api } from './client';
import type {
  Analysis,
  AnalysisDetail,
  AnalysisStatusRead,
  AnalyticsReport,
  ChatRequest,
  ChatResponse,
  ComparisonResult,
  CountryRisk,
  HistoricalReport,
  KpiSummary,
  LoginPayload,
  Page,
  RegisterPayload,
  RiskBreakdown,
  Shipment,
  Token,
  TrendAnalysis,
  Upload,
  UploadAccepted,
  User,
  VendorScore,
} from './types';

// ── Auth ──────────────────────────────────────────────────────────────

export const authApi = {
  register: (payload: RegisterPayload) =>
    api.post<Token>('/auth/register', payload, { anonymous: true }),

  login: (payload: LoginPayload) =>
    api.post<Token>('/auth/login', payload, { anonymous: true }),

  me: () => api.get<User>('/auth/me'),
};

// ── Uploads ───────────────────────────────────────────────────────────

export const uploadsApi = {
  create: (file: File, label?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (label) formData.append('label', label);
    return api.postForm<UploadAccepted>('/uploads', formData);
  },

  list: (limit = 50, offset = 0) =>
    api.get<Page<Upload>>(`/uploads?limit=${limit}&offset=${offset}`),

  get: (uploadId: string) => api.get<Upload>(`/uploads/${uploadId}`),

  shipments: (uploadId: string, limit = 100, offset = 0) =>
    api.get<Page<Shipment>>(
      `/uploads/${uploadId}/shipments?limit=${limit}&offset=${offset}`,
    ),

  /** Most recent analysis for an upload — the link a bookmarked URL needs. */
  latestAnalysis: (uploadId: string) =>
    api.get<AnalysisDetail>(`/uploads/${uploadId}/analysis`),

  remove: (uploadId: string) => api.delete<{ message: string }>(`/uploads/${uploadId}`),

  sample: () =>
    api.get<{ csv: string; filename: string }>('/uploads/sample'),
};

// ── Analyses ──────────────────────────────────────────────────────────

export const analysesApi = {
  list: (limit = 50, offset = 0) =>
    api.get<Page<Analysis>>(`/analyses?limit=${limit}&offset=${offset}`),

  get: (analysisId: string) => api.get<AnalysisDetail>(`/analyses/${analysisId}`),

  status: (analysisId: string) =>
    api.get<AnalysisStatusRead>(`/analyses/${analysisId}/status`),

  rerun: (analysisId: string) =>
    api.post<AnalysisStatusRead>(`/analyses/${analysisId}/rerun`),

  compare: (beforeUploadId: string, afterUploadId: string) =>
    api.post<ComparisonResult>('/analyses/compare', {
      before_upload_id: beforeUploadId,
      after_upload_id: afterUploadId,
    }),
};

// ── Analytics (no AI call behind any of these) ────────────────────────

export const analyticsApi = {
  report: (uploadId: string) =>
    api.get<AnalyticsReport>(`/analytics/uploads/${uploadId}`),

  kpis: (uploadId: string) => api.get<KpiSummary>(`/analytics/uploads/${uploadId}/kpis`),

  vendors: (uploadId: string, limit = 25) =>
    api.get<VendorScore[]>(`/analytics/uploads/${uploadId}/vendors?limit=${limit}`),

  countries: (uploadId: string, limit = 25) =>
    api.get<CountryRisk[]>(`/analytics/uploads/${uploadId}/countries?limit=${limit}`),

  trend: (uploadId: string) =>
    api.get<TrendAnalysis>(`/analytics/uploads/${uploadId}/trend`),

  risk: (uploadId: string) =>
    api.get<RiskBreakdown>(`/analytics/uploads/${uploadId}/risk`),

  history: () => api.get<HistoricalReport>('/analytics/history'),
};

// ── Chat ──────────────────────────────────────────────────────────────

export const chatApi = {
  ask: (payload: ChatRequest) => api.post<ChatResponse>('/chat', payload),
};

// ── Query keys ────────────────────────────────────────────────────────
// Centralised so invalidation after a mutation can't drift out of sync with
// the key a query was registered under.

export const queryKeys = {
  me: ['me'] as const,
  uploads: (limit: number, offset: number) => ['uploads', limit, offset] as const,
  upload: (id: string) => ['upload', id] as const,
  shipments: (id: string, offset: number) => ['shipments', id, offset] as const,
  analyses: ['analyses'] as const,
  analysis: (id: string) => ['analysis', id] as const,
  analysisStatus: (id: string) => ['analysis-status', id] as const,
  report: (id: string) => ['report', id] as const,
  history: ['history'] as const,
};
