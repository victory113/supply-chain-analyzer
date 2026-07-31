import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from 'recharts';

import type { RiskBreakdown } from '@/api/types';
import { CHART_COLORS, formatPercent, humanizeKey, riskColor } from '@/lib/format';

/**
 * Composite risk score as a half gauge, with its weighted drivers underneath.
 *
 * The drivers matter as much as the number: showing component × weight is what
 * turns "68/100" into something a user can act on.
 */
export function RiskGauge({ risk }: { risk: RiskBreakdown }) {
  const color = riskColor(risk.level);
  const data = [{ name: 'risk', value: risk.score, fill: color }];

  // Rank by contribution, not raw component value — a high component with a
  // small weight isn't what's driving the score.
  const drivers = Object.entries(risk.weights)
    .map(([key, weight]) => ({
      key,
      contribution: (risk.components[key] ?? 0) * weight * 100,
      component: risk.components[key] ?? 0,
    }))
    .sort((a, b) => b.contribution - a.contribution);

  const maxContribution = Math.max(...drivers.map((d) => d.contribution), 0.0001);

  return (
    <div>
      <div style={{ position: 'relative', height: 150 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            innerRadius="72%"
            outerRadius="100%"
            data={data}
            startAngle={180}
            endAngle={0}
            barSize={16}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar
              dataKey="value"
              background={{ fill: CHART_COLORS.grid }}
              cornerRadius={8}
              isAnimationActive={false}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'flex-end',
            paddingBottom: 8,
            pointerEvents: 'none',
          }}
        >
          <div
            style={{
              fontSize: 34,
              fontWeight: 700,
              color,
              fontVariantNumeric: 'tabular-nums',
              lineHeight: 1,
            }}
          >
            {risk.score.toFixed(0)}
          </div>
          <div className="tiny faint">out of 100</div>
        </div>
      </div>

      <div className="stack" style={{ gap: 8, marginTop: 12 }}>
        <div className="tiny faint">Weighted drivers</div>
        {drivers.map((driver) => (
          <div key={driver.key} className="row" style={{ gap: 10, flexWrap: 'nowrap' }}>
            <span className="tiny grow" style={{ minWidth: 0 }}>
              {humanizeKey(driver.key)}
            </span>
            <span className="bar-track grow" style={{ maxWidth: 120 }}>
              <span
                className="bar-fill"
                style={{
                  width: `${(driver.contribution / maxContribution) * 100}%`,
                  background: color,
                  display: 'block',
                }}
              />
            </span>
            <span className="tiny nums faint" style={{ width: 52, textAlign: 'right' }}>
              {formatPercent(driver.component * 100, 0)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
