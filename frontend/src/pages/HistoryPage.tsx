import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { analyticsApi, queryKeys } from '@/api/endpoints';
import { HistoryChart } from '@/components/charts/HistoryChart';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import {
  TREND_LABELS,
  formatDate,
  formatNumber,
  formatPercent,
  levelFromScore,
  riskTone,
  trendTone,
} from '@/lib/format';

/**
 * Cross-upload view — "how has our supply chain changed over the last year?"
 *
 * Assembled server-side from stored analyses rather than re-scanning every
 * shipment, so it stays cheap as history grows.
 */
export function HistoryPage() {
  const historyQuery = useQuery({
    queryKey: queryKeys.history,
    queryFn: () => analyticsApi.history(),
  });

  if (historyQuery.isPending) return <LoadingState label="Loading history" />;
  if (historyQuery.isError) {
    return <ErrorState error={historyQuery.error} onRetry={() => void historyQuery.refetch()} />;
  }

  const history = historyQuery.data;

  if (history.points.length < 2) {
    return (
      <div className="stack">
        <header className="page-header">
          <div>
            <h1 className="page-title">History</h1>
            <p className="page-subtitle">Performance across every analysed dataset.</p>
          </div>
        </header>
        <EmptyState
          icon="📅"
          title="Not enough history yet"
          body={history.summary}
          action={
            <Link to="/uploads" className="btn">
              Upload another dataset
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">History</h1>
          <p className="page-subtitle">{history.points.length} analysed datasets</p>
        </div>
        <Badge tone={trendTone(history.direction)}>{TREND_LABELS[history.direction]}</Badge>
      </header>

      <Card title="Risk score over time" hint={history.summary}>
        <HistoryChart points={history.points} />
      </Card>

      <Card title="Dataset comparison">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Uploaded</th>
                <th className="num">Rows</th>
                <th className="num">Risk score</th>
                <th className="num">Late</th>
                <th className="num">Avg delay</th>
                <th className="num">Success rate</th>
              </tr>
            </thead>
            <tbody>
              {history.points.map((point) => (
                <tr key={point.upload_id}>
                  <td>
                    <Link
                      to={`/uploads/${point.upload_id}`}
                      style={{ color: 'var(--accent)' }}
                    >
                      {point.label ?? 'Untitled'}
                    </Link>
                  </td>
                  <td>{formatDate(point.uploaded_at)}</td>
                  <td className="num">{formatNumber(point.row_count)}</td>
                  <td className="num">
                    <Badge tone={riskTone(levelFromScore(point.risk_score))}>
                      {point.risk_score.toFixed(0)}
                    </Badge>
                  </td>
                  <td className="num">{formatPercent(point.late_shipment_pct, 0)}</td>
                  <td className="num">{point.avg_delay_days.toFixed(1)}d</td>
                  <td className="num">{formatPercent(point.delivery_success_rate, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
