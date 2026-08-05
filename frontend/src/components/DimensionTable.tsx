import type { DimensionScore } from '@/api/types';
import { Card } from '@/components/ui/Card';
import { formatCurrency, formatDays, formatNumber, formatPercent } from '@/lib/format';

interface DimensionTableProps {
  title: string;
  hint: string;
  rows: DimensionScore[];
  /** Column header for the first column — "Carrier", "Mode", "Lane". */
  label: string;
}

/**
 * A performance breakdown for one dimension.
 *
 * Renders nothing at all when `rows` is empty. That is the whole contract: the
 * backend omits a section when the upload had no column for it, and showing an
 * empty "Carrier performance" card would imply the question was asked and came
 * back blank, rather than never having been answerable.
 */
export function DimensionTable({ title, hint, rows, label }: DimensionTableProps) {
  if (rows.length === 0) return null;

  const worst = rows[0];

  return (
    <Card title={title} hint={hint}>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{label}</th>
              <th className="num">Share</th>
              <th className="num">Shipments</th>
              <th className="num">Late</th>
              <th className="num">Avg delay</th>
              <th className="num">Avg freight</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td className="num faint">{formatPercent(row.share_pct, 0)}</td>
                <td className="num">{formatNumber(row.shipment_count)}</td>
                <td className="num">
                  <span style={{ color: row.late_pct > 40 ? 'var(--high)' : undefined }}>
                    {formatPercent(row.late_pct)}
                  </span>
                </td>
                <td className="num">{formatDays(row.avg_delay_days)}</td>
                {/* An em dash, not $0 — this group had no freight data. */}
                <td className="num faint">
                  {row.avg_freight_cost === null ? '—' : formatCurrency(row.avg_freight_cost)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {worst && rows.length > 1 && (
        <p className="tiny faint" style={{ marginTop: 10 }}>
          {worst.label} is the worst performer at {formatPercent(worst.late_pct)} late across{' '}
          {formatNumber(worst.shipment_count)} shipments.
        </p>
      )}
    </Card>
  );
}
