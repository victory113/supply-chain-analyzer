import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { TrendPoint } from '@/api/types';
import { CHART_COLORS, formatDays, formatPercent, formatPeriod } from '@/lib/format';

import { ChartTooltip } from './ChartTooltip';

/**
 * Shipment volume (bars) against average delay (line) per month.
 *
 * Plotted on the same axes deliberately: a delay spike matters much more when
 * it lands on a high-volume month, and separate charts hide that.
 */
export function DelayTrendChart({ points }: { points: TrendPoint[] }) {
  const data = points.map((point) => ({
    period: point.period,
    label: formatPeriod(point.period),
    shipments: point.shipment_count,
    avgDelay: point.avg_delay_days,
    latePct: point.late_pct,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
        <XAxis
          dataKey="label"
          stroke={CHART_COLORS.axis}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: CHART_COLORS.grid }}
        />
        <YAxis
          yAxisId="left"
          stroke={CHART_COLORS.axis}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          yAxisId="right"
          orientation="right"
          stroke={CHART_COLORS.axis}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          cursor={{ fill: 'rgba(255,255,255,0.04)' }}
          content={
            <ChartTooltip
              formatters={{
                shipments: (value) => `${value}`,
                avgDelay: (value) => formatDays(value),
                latePct: (value) => formatPercent(value),
              }}
            />
          }
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar
          yAxisId="left"
          dataKey="shipments"
          name="Shipments"
          fill={CHART_COLORS.accentSoft}
          stroke={CHART_COLORS.accent}
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="avgDelay"
          name="Avg delay (days)"
          stroke="#ffb347"
          strokeWidth={2}
          dot={{ r: 3 }}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
