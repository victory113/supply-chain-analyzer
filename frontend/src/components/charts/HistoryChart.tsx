import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { HistoricalPoint } from '@/api/types';
import { CHART_COLORS, formatDate, formatPercent, truncate } from '@/lib/format';

import { ChartTooltip } from './ChartTooltip';

/**
 * Composite risk score and late-shipment rate across every analysed upload —
 * the "how has our supply chain changed over the year?" view.
 */
export function HistoryChart({ points }: { points: HistoricalPoint[] }) {
  const data = points.map((point) => ({
    label: truncate(point.label ?? formatDate(point.uploaded_at), 16),
    uploadedAt: formatDate(point.uploaded_at),
    riskScore: point.risk_score,
    latePct: point.late_shipment_pct,
    successRate: point.delivery_success_rate,
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <defs>
          <linearGradient id="riskGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART_COLORS.accent} stopOpacity={0.45} />
            <stop offset="100%" stopColor={CHART_COLORS.accent} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
        <XAxis
          dataKey="label"
          stroke={CHART_COLORS.axis}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: CHART_COLORS.grid }}
        />
        <YAxis
          domain={[0, 100]}
          stroke={CHART_COLORS.axis}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          content={
            <ChartTooltip
              formatters={{
                riskScore: (value) => `${value.toFixed(1)}/100`,
                latePct: (value) => formatPercent(value),
                successRate: (value) => formatPercent(value),
              }}
            />
          }
        />
        <Area
          type="monotone"
          dataKey="riskScore"
          name="Risk score"
          stroke={CHART_COLORS.accent}
          strokeWidth={2}
          fill="url(#riskGradient)"
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="latePct"
          name="Late shipments"
          stroke="#ffb347"
          strokeWidth={2}
          dot={{ r: 3 }}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
