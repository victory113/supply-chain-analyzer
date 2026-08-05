import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';

import { analyticsApi, queryKeys, uploadsApi } from '@/api/endpoints';
import { KpiGrid } from '@/components/KpiGrid';
import { UploadDropzone } from '@/components/UploadDropzone';
import { CountryExposure } from '@/components/charts/CountryExposure';
import { DelayTrendChart } from '@/components/charts/DelayTrendChart';
import { RiskGauge } from '@/components/charts/RiskGauge';
import { VendorHealthChart } from '@/components/charts/VendorHealthChart';
import { Badge, RiskBadge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, InlineError, LoadingState } from '@/components/ui/States';
import { useAuth } from '@/auth/useAuth';
import { TREND_LABELS, formatRelative, trendTone } from '@/lib/format';

/**
 * Landing view: the most recent dataset at a glance.
 *
 * Deliberately reuses the same analytics endpoints as the detail page rather
 * than adding a bespoke "dashboard" endpoint — one source of truth for every
 * number, and one cache entry serving both screens.
 */
export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const uploadsQuery = useQuery({
    queryKey: queryKeys.uploads(5, 0),
    queryFn: () => uploadsApi.list(5, 0),
  });

  const latestUpload = uploadsQuery.data?.items[0];

  const reportQuery = useQuery({
    queryKey: queryKeys.report(latestUpload?.id ?? 'none'),
    queryFn: () => analyticsApi.report(latestUpload!.id),
    enabled: Boolean(latestUpload),
  });

  const historyQuery = useQuery({
    queryKey: queryKeys.history,
    queryFn: () => analyticsApi.history(),
  });

  const createMutation = useMutation({
    mutationFn: (file: File) => uploadsApi.create(file),
    onSuccess: (accepted) => {
      void queryClient.invalidateQueries({ queryKey: ['uploads'] });
      navigate(`/uploads/${accepted.upload.id}`, { state: { ingest: accepted.ingest } });
    },
  });

  async function loadSample() {
    const sample = await uploadsApi.sample();
    createMutation.mutate(new File([sample.csv], sample.filename, { type: 'text/csv' }));
  }

  if (uploadsQuery.isPending) return <LoadingState label="Loading your data" />;
  if (uploadsQuery.isError) {
    return <ErrorState error={uploadsQuery.error} onRetry={() => void uploadsQuery.refetch()} />;
  }

  const greeting = user?.full_name ? `Welcome back, ${user.full_name.split(' ')[0]}` : 'Dashboard';

  if (!latestUpload) {
    return (
      <div className="stack">
        <header className="page-header">
          <div>
            <h1 className="page-title">{greeting}</h1>
            <p className="page-subtitle">Upload your first dataset to get started.</p>
          </div>
        </header>

        <UploadDropzone
          onFile={(file) => createMutation.mutate(file)}
          disabled={createMutation.isPending}
        />
        <InlineError error={createMutation.error} />

        <EmptyState
          icon="📈"
          title="Nothing analysed yet"
          body="Drop a shipment CSV above and you'll get computed risk metrics immediately, with an AI-written explanation a few seconds later."
          action={
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void loadSample()}
              disabled={createMutation.isPending}
            >
              Try sample data
            </button>
          }
        />
      </div>
    );
  }

  const report = reportQuery.data;
  const history = historyQuery.data;

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">{greeting}</h1>
          <p className="page-subtitle">
            Showing <strong>{latestUpload.label ?? latestUpload.filename}</strong> ·
            uploaded {formatRelative(latestUpload.created_at)}
          </p>
        </div>
        <div className="row">
          <Link to={`/uploads/${latestUpload.id}`} className="btn btn-secondary btn-sm">
            Full report
          </Link>
          <Link to="/uploads" className="btn btn-ghost btn-sm">
            Upload another
          </Link>
        </div>
      </header>

      {reportQuery.isPending && <LoadingState label="Computing metrics" />}
      {reportQuery.isError && (
        <ErrorState error={reportQuery.error} onRetry={() => void reportQuery.refetch()} />
      )}

      {report && (
        <>
          <KpiGrid kpis={report.kpis} />

          <div className="grid grid-2">
            <Card
              title="Composite risk"
              hint="Deterministic score, weights shown below"
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
                <p className="small muted">No dated rows, so no trend to plot.</p>
              )}
            </Card>
          </div>

          <div className="grid grid-2">
            <Card
              title="Vendors needing attention"
              hint="Lowest health scores"
              action={
                <Link to={`/uploads/${latestUpload.id}`} className="tiny" style={{ color: 'var(--accent)' }}>
                  See all
                </Link>
              }
            >
              {report.vendors.length > 0 ? (
                <VendorHealthChart vendors={report.vendors} limit={6} />
              ) : (
                <p className="small muted">Not enough repeat vendors to rank.</p>
              )}
            </Card>

            <Card title="Geographic exposure" hint="By origin country">
              <CountryExposure countries={report.countries} limit={6} />
            </Card>
          </div>
        </>
      )}

      {history && history.points.length >= 2 && (
        <Card
          title="Across all uploads"
          hint={history.summary}
          action={
            <Link to="/history" className="tiny" style={{ color: 'var(--accent)' }}>
              Full history
            </Link>
          }
        >
          <Badge tone={trendTone(history.direction)}>{TREND_LABELS[history.direction]}</Badge>
        </Card>
      )}
    </div>
  );
}
