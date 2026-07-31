import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { analysesApi, queryKeys, uploadsApi } from '@/api/endpoints';
import type { AnalyticsReport, ComparisonChange } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, InlineError, LoadingState } from '@/components/ui/States';
import { formatCurrency, formatDays, formatPercent, formatRelative } from '@/lib/format';

const CHANGE_TONE: Record<ComparisonChange['change_type'], 'low' | 'high' | 'medium'> = {
  IMPROVED: 'low',
  WORSENED: 'high',
  NEW_ISSUE: 'medium',
};

export function ComparePage() {
  const [beforeId, setBeforeId] = useState('');
  const [afterId, setAfterId] = useState('');

  const uploadsQuery = useQuery({
    queryKey: queryKeys.uploads(100, 0),
    queryFn: () => uploadsApi.list(100, 0),
  });

  const compareMutation = useMutation({
    mutationFn: () => analysesApi.compare(beforeId, afterId),
  });

  if (uploadsQuery.isPending) return <LoadingState label="Loading datasets" />;
  if (uploadsQuery.isError) {
    return <ErrorState error={uploadsQuery.error} onRetry={() => void uploadsQuery.refetch()} />;
  }

  const uploads = uploadsQuery.data.items;
  const canCompare = beforeId !== '' && afterId !== '' && beforeId !== afterId;

  if (uploads.length < 2) {
    return (
      <div className="stack">
        <header className="page-header">
          <div>
            <h1 className="page-title">Compare</h1>
            <p className="page-subtitle">Diff two datasets to see what changed.</p>
          </div>
        </header>
        <EmptyState
          icon="⚖️"
          title="Two datasets needed"
          body="Upload at least two CSVs — typically before and after a disruption — and this will show exactly what moved."
        />
      </div>
    );
  }

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Compare</h1>
          <p className="page-subtitle">
            Pick a before and an after. Metrics are recomputed; the model only
            explains the difference.
          </p>
        </div>
      </header>

      <Card title="Select datasets">
        <div className="grid grid-2">
          <div className="field">
            <label className="field-label" htmlFor="before-select">
              Before
            </label>
            <select
              id="before-select"
              className="select"
              value={beforeId}
              onChange={(event) => setBeforeId(event.target.value)}
            >
              <option value="">Choose a dataset…</option>
              {uploads.map((upload) => (
                <option key={upload.id} value={upload.id}>
                  {upload.label ?? upload.filename} · {formatRelative(upload.created_at)}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="after-select">
              After
            </label>
            <select
              id="after-select"
              className="select"
              value={afterId}
              onChange={(event) => setAfterId(event.target.value)}
            >
              <option value="">Choose a dataset…</option>
              {uploads.map((upload) => (
                <option key={upload.id} value={upload.id}>
                  {upload.label ?? upload.filename} · {formatRelative(upload.created_at)}
                </option>
              ))}
            </select>
          </div>
        </div>

        {beforeId !== '' && beforeId === afterId && (
          <p className="field-error" style={{ marginTop: 8 }}>
            Pick two different datasets.
          </p>
        )}

        <div className="row" style={{ marginTop: 14 }}>
          <button
            type="button"
            className="btn"
            disabled={!canCompare || compareMutation.isPending}
            onClick={() => compareMutation.mutate()}
          >
            {compareMutation.isPending ? 'Comparing…' : 'Compare'}
          </button>
        </div>

        <div style={{ marginTop: 12 }}>
          <InlineError error={compareMutation.error} />
        </div>
      </Card>

      {compareMutation.isPending && <LoadingState label="Analysing the difference" />}

      {compareMutation.data && (
        <>
          <Card
            title="What changed"
            hint={compareMutation.data.summary}
            action={<Badge tone="accent">{compareMutation.data.net_change}</Badge>}
          >
            {compareMutation.data.changes.length === 0 ? (
              <p className="small muted">No material changes were identified.</p>
            ) : (
              <div className="stack" style={{ gap: 12 }}>
                {compareMutation.data.changes.map((change) => (
                  <article key={change.title} className="risk-item">
                    <div className="row-between">
                      <h3 className="risk-title">{change.title}</h3>
                      <Badge tone={CHANGE_TONE[change.change_type]}>
                        {change.change_type.replace('_', ' ')}
                      </Badge>
                    </div>
                    <p className="risk-text">{change.explanation}</p>
                    {change.recommendation && (
                      <p className="risk-recommendation">
                        <strong>Do this: </strong>
                        {change.recommendation}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </Card>

          <Card title="Metric-by-metric" hint="Computed values, not model output">
            <MetricDiff before={compareMutation.data.before} after={compareMutation.data.after} />
          </Card>
        </>
      )}
    </div>
  );
}

interface MetricRow {
  label: string;
  before: number;
  after: number;
  format: (value: number) => string;
  /** True when a rise is bad (delays), false when a rise is good (success rate). */
  higherIsWorse: boolean;
}

function MetricDiff({ before, after }: { before: AnalyticsReport; after: AnalyticsReport }) {
  const rows: MetricRow[] = [
    {
      label: 'Composite risk score',
      before: before.risk.score,
      after: after.risk.score,
      format: (v) => v.toFixed(1),
      higherIsWorse: true,
    },
    {
      label: 'Late shipments',
      before: before.kpis.late_shipment_pct,
      after: after.kpis.late_shipment_pct,
      format: (v) => formatPercent(v),
      higherIsWorse: true,
    },
    {
      label: 'Average delay',
      before: before.kpis.avg_delay_days,
      after: after.kpis.avg_delay_days,
      format: (v) => formatDays(v),
      higherIsWorse: true,
    },
    {
      label: 'p90 delay',
      before: before.kpis.p90_delay_days,
      after: after.kpis.p90_delay_days,
      format: (v) => formatDays(v),
      higherIsWorse: true,
    },
    {
      label: 'Delivery success rate',
      before: before.kpis.delivery_success_rate,
      after: after.kpis.delivery_success_rate,
      format: (v) => formatPercent(v),
      higherIsWorse: false,
    },
    {
      label: 'Value at risk',
      before: before.kpis.value_at_risk,
      after: after.kpis.value_at_risk,
      format: (v) => formatCurrency(v),
      higherIsWorse: true,
    },
    {
      label: 'Distinct vendors',
      before: before.kpis.distinct_vendors,
      after: after.kpis.distinct_vendors,
      format: (v) => v.toFixed(0),
      higherIsWorse: false,
    },
  ];

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Metric</th>
            <th className="num">Before</th>
            <th className="num">After</th>
            <th className="num">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const delta = row.after - row.before;
            const worse = row.higherIsWorse ? delta > 0 : delta < 0;
            const color =
              Math.abs(delta) < 0.05
                ? 'var(--text-muted)'
                : worse
                  ? 'var(--high)'
                  : 'var(--low)';

            return (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td className="num">{row.format(row.before)}</td>
                <td className="num">{row.format(row.after)}</td>
                <td className="num" style={{ color }}>
                  {delta > 0 ? '+' : ''}
                  {row.format(delta)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
