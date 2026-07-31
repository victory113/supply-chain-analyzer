import type { CountryRisk } from '@/api/types';
import { formatCurrency, formatDays, formatPercent, riskColor } from '@/lib/format';

/**
 * Geographic exposure by origin country.
 *
 * Deliberately a ranked exposure panel rather than a choropleth: a world map
 * would need a vendored topojson (~100KB) and would render most of the globe
 * as empty space, since a typical dataset covers 3-10 origins. This shows the
 * same three facts per country — volume share, risk score, and delay — in a
 * form that stays readable at any dataset size.
 */
export function CountryExposure({
  countries,
  limit = 8,
}: {
  countries: CountryRisk[];
  limit?: number;
}) {
  if (countries.length === 0) {
    return <p className="small muted">No origin-country data in this dataset.</p>;
  }

  const shown = countries.slice(0, limit);
  const totalShipments = countries.reduce((sum, c) => sum + c.shipment_count, 0);

  return (
    <div className="stack" style={{ gap: 14 }}>
      {shown.map((country) => {
        const share = totalShipments > 0 ? (country.shipment_count / totalShipments) * 100 : 0;
        const color = riskColor(country.risk_level);

        return (
          <div key={country.country}>
            <div className="row-between" style={{ marginBottom: 5 }}>
              <span className="small" style={{ fontWeight: 500 }}>
                {country.country}
              </span>
              <span className="tiny nums" style={{ color }}>
                risk {country.risk_score.toFixed(0)}
              </span>
            </div>

            <div className="bar-track" style={{ height: 8 }}>
              <span
                className="bar-fill"
                style={{ width: `${share}%`, background: color, display: 'block' }}
              />
            </div>

            <div className="row-between tiny faint" style={{ marginTop: 4 }}>
              <span>
                {country.shipment_count} shipments · {formatPercent(share, 0)} of volume
              </span>
              <span>
                {formatPercent(country.late_pct, 0)} late · {formatDays(country.avg_delay_days)}{' '}
                avg · {formatCurrency(country.total_value)}
              </span>
            </div>
          </div>
        );
      })}

      {countries.length > limit && (
        <p className="tiny faint">
          + {countries.length - limit} more origin{countries.length - limit === 1 ? '' : 's'}
        </p>
      )}
    </div>
  );
}
