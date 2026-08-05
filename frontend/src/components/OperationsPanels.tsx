import type { CostSummary, EmissionsSummary, QualitySummary } from '@/api/types';
import { Card } from '@/components/ui/Card';
import { formatCurrency, formatNumber, formatPercent } from '@/lib/format';

/**
 * Each panel returns null when the backend sent no summary, and each *stat*
 * inside it is skipped when its own value is null. A file can carry freight
 * costs but no weights, damage flags but no fill quantities — so partial data
 * has to render partially rather than filling the gaps with zeros.
 */

interface StatProps {
  label: string;
  value: string;
  hint?: string;
}

function Stat({ label, value, hint }: StatProps) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}

function CoverageNote({ pct }: { pct: number }) {
  if (pct >= 99) return null;
  // Below full coverage the user needs to know the figure describes a subset.
  return (
    <p className="tiny faint" style={{ marginTop: 10 }}>
      Computed from the {formatPercent(pct, 0)} of rows that carried this data.
    </p>
  );
}

export function CostPanel({ cost }: { cost: CostSummary | null }) {
  if (!cost) return null;

  return (
    <Card title="Freight economics" hint="What movement costs, and what lateness costs">
      <div className="grid grid-kpi">
        <Stat label="Total freight" value={formatCurrency(cost.total_freight_cost)} />
        <Stat label="Avg per shipment" value={formatCurrency(cost.avg_freight_cost)} />
        {cost.freight_pct_of_goods !== null && (
          <Stat
            label="Freight vs goods"
            value={formatPercent(cost.freight_pct_of_goods)}
            hint="Share of goods value spent on moving them"
          />
        )}
        {cost.freight_per_unit !== null && (
          <Stat label="Per unit" value={formatCurrency(cost.freight_per_unit)} />
        )}
        {cost.freight_per_kg !== null && (
          <Stat label="Per kg" value={formatCurrency(cost.freight_per_kg)} />
        )}
        <Stat
          label="Spent on late shipments"
          value={formatCurrency(cost.freight_spent_on_late_shipments)}
          hint="Freight paid on deliveries that still arrived late"
        />
      </div>
      <CoverageNote pct={cost.coverage_pct} />
    </Card>
  );
}

export function QualityPanel({ quality }: { quality: QualitySummary | null }) {
  if (!quality) return null;

  return (
    <Card title="Order quality" hint="Beyond punctuality — did the goods arrive intact and complete?">
      <div className="grid grid-kpi">
        <Stat
          label="Perfect order rate"
          value={formatPercent(quality.perfect_order_rate_pct)}
          hint="On time, undamaged, not returned, fully filled"
        />
        {quality.damage_rate_pct !== null && (
          <Stat
            label="Damage rate"
            value={formatPercent(quality.damage_rate_pct)}
            hint={`${formatNumber(quality.damaged_count ?? 0)} shipments`}
          />
        )}
        {quality.return_rate_pct !== null && (
          <Stat
            label="Return rate"
            value={formatPercent(quality.return_rate_pct)}
            hint={`${formatNumber(quality.returned_count ?? 0)} shipments`}
          />
        )}
        {quality.avg_fill_rate_pct !== null && (
          <Stat
            label="Avg fill rate"
            value={formatPercent(quality.avg_fill_rate_pct)}
            hint="Share of ordered quantity delivered"
          />
        )}
      </div>
      <CoverageNote pct={quality.coverage_pct} />
    </Card>
  );
}

export function EmissionsPanel({ emissions }: { emissions: EmissionsSummary | null }) {
  if (!emissions) return null;

  const byMode = Object.entries(emissions.co2_by_mode_kg);

  return (
    <Card title="Carbon footprint" hint="From the file's own data, or estimated from mode and distance">
      <div className="grid grid-kpi">
        <Stat label="Total CO₂e" value={`${formatNumber(Math.round(emissions.total_co2_kg))} kg`} />
        <Stat
          label="Per shipment"
          value={`${emissions.avg_co2_per_shipment_kg.toFixed(1)} kg`}
        />
      </div>

      {byMode.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 14 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Transport mode</th>
                <th className="num">CO₂e</th>
              </tr>
            </thead>
            <tbody>
              {byMode.map(([mode, kg]) => (
                <tr key={mode}>
                  <td style={{ textTransform: 'capitalize' }}>{mode}</td>
                  <td className="num">{formatNumber(Math.round(kg))} kg</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CoverageNote pct={emissions.coverage_pct} />
      <p className="tiny faint" style={{ marginTop: 8 }}>
        Estimates use published average emission factors per tonne-kilometre and are
        indicative, not a certified carbon calculation.
      </p>
    </Card>
  );
}
