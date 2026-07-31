/**
 * Shared tooltip for every Recharts chart.
 *
 * Recharts' default tooltip renders on a white background, which is unreadable
 * against this theme, so all charts pass this instead.
 */

export interface TooltipPayloadItem {
  name?: string;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
}

export interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string | number;
  /** Per-series value formatting, keyed by dataKey. */
  formatters?: Record<string, (value: number) => string>;
  labelFormatter?: (label: string) => string;
}

export function ChartTooltip({
  active,
  payload,
  label,
  formatters,
  labelFormatter,
}: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const heading =
    typeof label === 'string' && labelFormatter ? labelFormatter(label) : label;

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-strong)',
        borderRadius: 8,
        padding: '9px 12px',
        fontSize: 12,
        boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
      }}
    >
      {heading !== undefined && (
        <div style={{ marginBottom: 6, fontWeight: 600 }}>{heading}</div>
      )}
      {payload.map((item, index) => {
        const key = String(item.dataKey ?? index);
        const raw = typeof item.value === 'number' ? item.value : Number(item.value);
        const formatted =
          formatters?.[key] && Number.isFinite(raw)
            ? formatters[key]!(raw)
            : String(item.value ?? '—');

        return (
          <div
            key={key}
            style={{ display: 'flex', gap: 10, justifyContent: 'space-between' }}
          >
            <span style={{ color: item.color ?? 'var(--text-muted)' }}>{item.name}</span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatted}</span>
          </div>
        );
      })}
    </div>
  );
}
