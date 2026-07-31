import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { VendorScore } from '@/api/types';
import { CHART_COLORS, riskColor, truncate } from '@/lib/format';

import { ChartTooltip } from './ChartTooltip';

/**
 * Vendor health scores, worst first.
 *
 * Horizontal bars because vendor names are long and would collide on a
 * vertical axis; each bar is coloured by the risk level the backend derived
 * from that same score, so chart and badge can never disagree.
 */
export function VendorHealthChart({
  vendors,
  limit = 8,
}: {
  vendors: VendorScore[];
  limit?: number;
}) {
  const data = vendors.slice(0, limit).map((vendor) => ({
    name: truncate(vendor.vendor, 22),
    fullName: vendor.vendor,
    health: vendor.health_score,
    latePct: vendor.late_pct,
    shipments: vendor.shipment_count,
    color: riskColor(vendor.risk_level),
  }));

  const height = Math.max(180, data.length * 34 + 40);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
      >
        <CartesianGrid stroke={CHART_COLORS.grid} horizontal={false} />
        <XAxis
          type="number"
          domain={[0, 100]}
          stroke={CHART_COLORS.axis}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          width={130}
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
                health: (value) => `${value.toFixed(0)}/100`,
              }}
            />
          }
        />
        <Bar dataKey="health" name="Health score" radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {data.map((entry) => (
            <Cell key={entry.fullName} fill={entry.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
