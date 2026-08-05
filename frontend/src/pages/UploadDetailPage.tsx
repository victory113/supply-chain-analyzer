import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';

import { ApiError } from '@/api/client';
import { analysesApi, analyticsApi, queryKeys, uploadsApi } from '@/api/endpoints';
import type { IngestReport } from '@/api/types';
import { AnalysisProgressBanner } from '@/components/AnalysisProgress';
import { DimensionTable } from '@/components/DimensionTable';
import { IngestSummary } from '@/components/IngestSummary';
import { CostPanel, EmissionsPanel, QualityPanel } from '@/components/OperationsPanels';
import { KpiGrid } from '@/components/KpiGrid';
import { RiskList } from '@/components/RiskList';
import { CountryExposure } from '@/components/charts/CountryExposure';
import { DelayTrendChart } from '@/components/charts/DelayTrendChart';
import { RiskGauge } from '@/components/charts/RiskGauge';
import { VendorHealthChart } from '@/components/charts/VendorHealthChart';
import { Badge, RiskBadge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { useAnalysisStatus } from '@/hooks/useAnalysisStatus';
import {
  TREND_LABELS,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
  trendTone,
} from '@/lib/format';

export function UploadDetailPage() {
  const { uploadId = '' } = useParams<{ uploadId: string }>();
  const queryClient = useQueryClient();

  // Present only when we arrived here straight from an upload; absent on a
  // reload or a visit from the list, which is fine — it's a one-time receipt.
  const { ingest } = (useLocation().state ?? {}) as { ingest?: IngestReport | null };

  const uploadQuery = useQuery({
    queryKey: queryKeys.upload(uploadId),
    queryFn: () => uploadsApi.get(uploadId),
    enabled: Boolean(uploadId),
  });

  // Analytics are computed server-side without the model, so this resolves
  // even while the AI narration is still queued.
  const reportQuery = useQuery({
    queryKey: queryKeys.report(uploadId),
    queryFn: () => analyticsApi.report(uploadId),
    enabled: Boolean(uploadId),
  });

  const analysisQuery = useQuery({
    queryKey: queryKeys.analysis(uploadId),
    queryFn: () => uploadsApi.latestAnalysis(uploadId),
    enabled: Boolean(uploadId),
    // A brand-new upload may not have an analysis row visible yet.
    retry: (count, error) =>
      error instanceof ApiError && error.isNotFound ? false : count < 2,
  });

  const analysisId = analysisQuery.data?.id ?? null;
  const loadedStatus = analysisQuery.data?.status;
  const alreadyTerminal = loadedStatus === 'completed' || loadedStatus === 'failed';

  const progress = useAnalysisStatus({
    analysisId,
    enabled: !alreadyTerminal,
    knownStatus: loadedStatus ?? null,
    knownError: analysisQuery.data?.error_message ?? null,
  });

  // Once polling reports a terminal state, refetch the full record so the
  // summary and risks appear. Done in an effect, not during render — an
  // invalidate in the render body re-enters the same render on every pass.
  const settled = progress.isComplete || progress.isFailed;
  useEffect(() => {
    if (settled && loadedStatus !== progress.status) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.analysis(uploadId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.report(uploadId) });
    }
  }, [settled, progress.status, loadedStatus, queryClient, uploadId]);

  const rerunMutation = useMutation({
    mutationFn: () => analysesApi.rerun(analysisId as string),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.analysis(uploadId) });
    },
  });

  if (!uploadId) return <ErrorState error={new Error('No upload specified.')} />;
  if (uploadQuery.isPending) return <LoadingState label="Loading dataset" />;
  if (uploadQuery.isError) {
    return <ErrorState error={uploadQuery.error} onRetry={() => void uploadQuery.refetch()} />;
  }

  const upload = uploadQuery.data;
  const analysis = analysisQuery.data;
  const report = reportQuery.data;

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">{upload.label ?? upload.filename}</h1>
          <p className="page-subtitle">
            {formatNumber(upload.row_count)} shipments · uploaded{' '}
            {formatDateTime(upload.created_at)}
            {upload.rejected_row_count > 0 &&
              ` · ${upload.rejected_row_count} rows rejected`}
          </p>
        </div>
        <div className="row">
          <Link to="/uploads" className="btn btn-ghost btn-sm">
            All uploads
          </Link>
          <Link to={`/chat?upload=${upload.id}`} className="btn btn-secondary btn-sm">
            Ask about this dataset
          </Link>
          {analysisId && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => rerunMutation.mutate()}
              disabled={rerunMutation.isPending || progress.isPending}
            >
              {rerunMutation.isPending ? 'Queuing…' : 'Re-run analysis'}
            </button>
          )}
        </div>
      </header>

      {ingest && <IngestSummary report={ingest} />}

      <AnalysisProgressBanner progress={progress} />

      {reportQuery.isPending && <LoadingState label="Computing metrics" />}
      {reportQuery.isError && (
        <ErrorState error={reportQuery.error} onRetry={() => void reportQuery.refetch()} />
      )}

      {report && (
        <>
          <KpiGrid kpis={report.kpis} />

          <div className="grid grid-2">
            <Card
              title="Composite risk score"
              // Not "fixed": a component the file can't support is dropped and
              // its weight redistributed, so the weights shown are the ones
              // actually used for this upload.
              hint="Computed in Python — every weight is shown below"
              action={<RiskBadge level={report.risk.level} />}
            >
              <RiskGauge risk={report.risk} />
            </Card>

            <Card
              title="Delay trend"
              hint={report.trend.commentary}
              action={
                <Badge tone={trendTone(report.trend.direction)}>
                  {TREND_LABELS[report.trend.direction]}
                </Badge>
              }
            >
              {report.trend.points.length > 0 ? (
                <DelayTrendChart points={report.trend.points} />
              ) : (
                <p className="small muted">
                  No usable dates in this dataset, so no trend can be plotted. Add a
                  shipped date or last-updated column to see month-by-month movement.
                </p>
              )}
            </Card>
          </div>

          <div className="grid grid-2">
            <Card title="Vendor health" hint="Worst performers first, 0–100">
              {report.vendors.length > 0 ? (
                <VendorHealthChart vendors={report.vendors} />
              ) : (
                <p className="small muted">
                  No vendor appears more than once, so no reliable ranking can be made.
                </p>
              )}
            </Card>

            <Card title="Geographic exposure" hint="By origin country">
              <CountryExposure countries={report.countries} />
            </Card>
          </div>

          {/* Everything below renders only if the upload carried the columns
              for it. A file with no carrier column simply has no carrier
              section — the alternative, a card full of zeros, would read as a
              finding rather than an absence. */}
          <CostPanel cost={report.cost} />
          <QualityPanel quality={report.quality} />

          <DimensionTable
            title="Carrier performance"
            hint="Who is actually delivering on time"
            label="Carrier"
            rows={report.carriers}
          />
          <DimensionTable
            title="Transport mode"
            hint="Air vs ocean vs road, on the same terms"
            label="Mode"
            rows={report.transport_modes}
          />
          <DimensionTable
            title="Service level"
            hint="Is the premium service earning its premium?"
            label="Service"
            rows={report.service_levels}
          />
          <DimensionTable
            title="Product categories"
            hint="Which goods run late most often"
            label="Category"
            rows={report.categories}
          />
          <DimensionTable
            title="Trade lanes"
            hint="Origin to destination, worst first"
            label="Lane"
            rows={report.lanes}
          />

          <EmissionsPanel emissions={report.emissions} />

          {report.healthy_signals.length > 0 && (
            <Card title="What's working" hint="Computed, not model-generated">
              <ul className="stack" style={{ gap: 6, paddingLeft: 18 }}>
                {report.healthy_signals.map((signal) => (
                  <li key={signal} className="small">
                    {signal}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}

      <Card
        title="AI risk assessment"
        hint={
          analysis?.model_name
            ? `${analysis.model_name} · ${formatDuration(analysis.duration_ms)}`
            : 'Generated from the computed metrics above'
        }
      >
        {analysisQuery.isPending && <LoadingState label="Loading analysis" />}

        {analysisQuery.isError && (
          <EmptyState
            icon="🤖"
            title="No analysis yet"
            body="The AI summary has not been generated for this dataset. All computed metrics above are unaffected."
          />
        )}

        {analysis && (
          <div className="stack">
            {analysis.summary && <p className="small">{analysis.summary}</p>}
            <RiskList risks={analysis.risks} />
          </div>
        )}
      </Card>

      {report && (
        <Card title="Vendor detail">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Vendor</th>
                  <th>Risk</th>
                  <th className="num">Health</th>
                  <th className="num">Shipments</th>
                  <th className="num">Late</th>
                  <th className="num">Avg delay</th>
                  <th className="num">Value at risk</th>
                </tr>
              </thead>
              <tbody>
                {report.vendors.map((vendor) => (
                  <tr key={vendor.vendor}>
                    <td>{vendor.vendor}</td>
                    <td>
                      <RiskBadge level={vendor.risk_level} />
                    </td>
                    <td className="num">{vendor.health_score.toFixed(0)}</td>
                    <td className="num">{vendor.shipment_count}</td>
                    <td className="num">{formatPercent(vendor.late_pct, 0)}</td>
                    <td className="num">{vendor.avg_delay_days.toFixed(1)}d</td>
                    <td className="num">${formatNumber(vendor.value_at_risk)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
