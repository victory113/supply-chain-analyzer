import type { KpiSummary } from '@/api/types';
import { formatCurrency, formatDays, formatNumber, formatPercent } from '@/lib/format';

interface KpiTileProps {
  label: string;
  value: string;
  hint?: string;
  tone?: 'high' | 'medium' | 'low';
}

export function KpiTile({ label, value, hint, tone }: KpiTileProps) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={tone ? `kpi-value ${tone}` : 'kpi-value'}>{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}

/** Thresholds mirror the backend's "healthy signal" cutoffs. */
function lateTone(pct: number): 'high' | 'medium' | 'low' {
  if (pct >= 40) return 'high';
  if (pct >= 15) return 'medium';
  return 'low';
}

function successTone(pct: number): 'high' | 'medium' | 'low' {
  if (pct >= 85) return 'low';
  if (pct >= 60) return 'medium';
  return 'high';
}

export function KpiGrid({ kpis }: { kpis: KpiSummary }) {
  return (
    <div className="grid grid-kpi">
      <KpiTile
        label="Shipments"
        value={formatNumber(kpis.total_shipments)}
        hint={`${kpis.distinct_vendors} vendors · ${kpis.distinct_countries} countries`}
      />
      <KpiTile
        label="Late shipments"
        value={formatPercent(kpis.late_shipment_pct)}
        hint={`${formatNumber(kpis.late_shipments)} of ${formatNumber(kpis.total_shipments)}`}
        tone={lateTone(kpis.late_shipment_pct)}
      />
      <KpiTile
        label="Avg delay"
        value={formatDays(kpis.avg_delay_days)}
        hint={`${formatDays(kpis.avg_delay_days_when_late)} when late · p90 ${formatDays(kpis.p90_delay_days)}`}
      />
      <KpiTile
        label="Delivery success"
        value={formatPercent(kpis.delivery_success_rate)}
        hint="Not delayed, critical, or cancelled"
        tone={successTone(kpis.delivery_success_rate)}
      />
      <KpiTile
        label="Value at risk"
        // No priced rows means no value to put at risk. "$0 of $0" would read
        // as "these shipments are worthless" rather than "we weren't told".
        value={kpis.total_value > 0 ? formatCurrency(kpis.value_at_risk) : '—'}
        hint={
          kpis.total_value > 0
            ? `of ${formatCurrency(kpis.total_value)} total`
            : 'No quantity or price column in this file'
        }
        tone={
          kpis.total_value > 0 && kpis.value_at_risk > kpis.total_value * 0.3
            ? 'high'
            : undefined
        }
      />
      <KpiTile
        label="Avg lead time"
        // A file with no lead-time column yields 0.0, and "0.0d" reads as a
        // measured value rather than an absent one. Say it's missing instead.
        value={kpis.avg_lead_time_days > 0 ? formatDays(kpis.avg_lead_time_days) : '—'}
        hint={
          kpis.avg_lead_time_days > 0
            ? `Median delay ${formatDays(kpis.median_delay_days)}`
            : 'No lead time column in this file'
        }
      />
    </div>
  );
}
