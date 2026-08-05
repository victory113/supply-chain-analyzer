import { useState } from 'react';

import type { IngestReport } from '@/api/types';
import { formatNumber } from '@/lib/format';

interface IngestSummaryProps {
  report: IngestReport;
}

/**
 * What the parser made of the uploaded file.
 *
 * Shown once, right after an upload. The point is that the app never silently
 * invents data: if a delay was computed from a date pair rather than read from
 * a column, or a column was ignored entirely, the user is told here — before
 * they start trusting the charts.
 */
export function IngestSummary({ report }: IngestSummaryProps) {
  const [showColumns, setShowColumns] = useState(false);

  const detected = Object.entries(report.detected_columns);
  const tone = report.warnings.length > 0 ? 'alert-warning' : 'alert-info';

  return (
    <div className={`alert ${tone}`}>
      <strong>
        Read {formatNumber(report.accepted_rows)} row
        {report.accepted_rows === 1 ? '' : 's'} · recognised {detected.length} column
        {detected.length === 1 ? '' : 's'}
      </strong>

      {report.derived_delays > 0 && (
        <div style={{ marginTop: 6 }}>
          Your file had no delay column, so delay was calculated from the scheduled
          and actual dates for {formatNumber(report.derived_delays)} row
          {report.derived_delays === 1 ? '' : 's'}.
        </div>
      )}

      {report.rejected_rows > 0 && (
        <div style={{ marginTop: 6 }}>
          {formatNumber(report.rejected_rows)} row
          {report.rejected_rows === 1 ? ' was' : 's were'} skipped as empty.
        </div>
      )}

      {report.warnings.map((warning) => (
        <div key={warning} style={{ marginTop: 6 }}>
          {warning}
        </div>
      ))}

      <button
        type="button"
        className="btn btn-ghost btn-sm"
        style={{ marginTop: 10 }}
        onClick={() => setShowColumns((open) => !open)}
        aria-expanded={showColumns}
      >
        {showColumns ? 'Hide column mapping' : 'Show column mapping'}
      </button>

      {showColumns && (
        <div style={{ marginTop: 10 }}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Your column</th>
                  <th>Used as</th>
                </tr>
              </thead>
              <tbody>
                {detected.map(([field, header]) => (
                  <tr key={field}>
                    <td className="mono">{header}</td>
                    <td className="faint">{field.replace(/_/g, ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {report.unmapped_columns.length > 0 && (
            <p className="tiny faint" style={{ marginTop: 8 }}>
              Ignored: {report.unmapped_columns.join(', ')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
