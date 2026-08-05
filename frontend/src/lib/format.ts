/** Display formatting. Pure functions, unit-tested. */

import type { RiskLevel, TrendDirection } from '@/api/types';

/** Shared with the backend's RiskLevel enum and the CSS custom properties. */
export const RISK_COLORS: Record<RiskLevel, string> = {
  HIGH: '#ff5c5c',
  MEDIUM: '#ffb347',
  LOW: '#4caf82',
};

export const CHART_COLORS = {
  accent: '#6c63ff',
  accentSoft: 'rgba(108, 99, 255, 0.2)',
  grid: '#2b3040',
  axis: '#6b7189',
  surface: '#171a23',
  border: '#2b3040',
  text: '#e8eaf0',
} as const;

export function riskClass(level: RiskLevel | null | undefined): string {
  if (!level) return 'neutral';
  return level.toLowerCase();
}

/** Badge/CSS tone for a risk level, without casting at every call site. */
export function riskTone(level: RiskLevel): 'high' | 'medium' | 'low' {
  switch (level) {
    case 'HIGH':
      return 'high';
    case 'MEDIUM':
      return 'medium';
    default:
      return 'low';
  }
}

export function riskColor(level: RiskLevel | null | undefined): string {
  return level ? RISK_COLORS[level] : CHART_COLORS.axis;
}

/** Maps a 0-100 score onto a level using the same thresholds as the backend. */
export function levelFromScore(score: number): RiskLevel {
  if (score >= 66) return 'HIGH';
  if (score >= 33) return 'MEDIUM';
  return 'LOW';
}

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  // Compact notation keeps KPI tiles readable; the exact figure is available
  // in the tooltip on charts that use this.
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  // Per-unit and per-kg figures are routinely under a dollar, and rounding
  // those to whole dollars renders a real $0.41 as "$0" — which reads as free.
  if (abs > 0 && abs < 100) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(0)}`;
}

export function formatDays(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toFixed(digits)}d`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** "3 days ago" — falls back to an absolute date beyond a month. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 2592000) return `${Math.floor(seconds / 86400)}d ago`;
  return formatDate(iso);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** "2024-03" → "Mar 2024" for chart axes. */
export function formatPeriod(period: string): string {
  const [year, month] = period.split('-');
  if (!year || !month) return period;
  const index = Number(month) - 1;
  const names = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return `${names[index] ?? month} ${year.slice(2)}`;
}

/** snake_case metric key → "Late rate", for the risk-driver breakdown. */
export function humanizeKey(key: string): string {
  const spaced = key.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export const TREND_LABELS: Record<TrendDirection, string> = {
  improving: 'Improving',
  worsening: 'Worsening',
  stable: 'Stable',
  insufficient_data: 'Not enough data',
};

/** Trend colouring is semantic, not literal: "worsening" is bad, so it's red. */
export function trendTone(direction: TrendDirection): 'high' | 'medium' | 'low' | 'neutral' {
  switch (direction) {
    case 'worsening':
      return 'high';
    case 'improving':
      return 'low';
    case 'stable':
      return 'medium';
    default:
      return 'neutral';
  }
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}
