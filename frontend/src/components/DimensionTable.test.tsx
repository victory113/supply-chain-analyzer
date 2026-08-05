import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { DimensionScore } from '@/api/types';

import { DimensionTable } from './DimensionTable';
import { CostPanel, EmissionsPanel, QualityPanel } from './OperationsPanels';

function row(overrides: Partial<DimensionScore> = {}): DimensionScore {
  return {
    label: 'UPS',
    shipment_count: 40,
    share_pct: 50,
    late_count: 8,
    late_pct: 20,
    avg_delay_days: 2.4,
    avg_transit_days: 5,
    total_value: 100000,
    avg_freight_cost: 120,
    ...overrides,
  };
}

describe('DimensionTable', () => {
  it('renders a row per dimension value', () => {
    render(
      <DimensionTable
        title="Carrier performance"
        hint="hint"
        label="Carrier"
        rows={[row(), row({ label: 'DHL', late_pct: 45 })]}
      />,
    );
    expect(screen.getByText('UPS')).toBeInTheDocument();
    expect(screen.getByText('DHL')).toBeInTheDocument();
  });

  it('renders nothing when the dimension has no data', () => {
    // The upload had no carrier column: the question was never answerable, so
    // the card must not appear at all.
    const { container } = render(
      <DimensionTable title="Carrier performance" hint="hint" label="Carrier" rows={[]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a dash rather than $0 when a group had no freight data', () => {
    render(
      <DimensionTable
        title="Carrier performance"
        hint="hint"
        label="Carrier"
        rows={[row({ avg_freight_cost: null }), row({ label: 'DHL', avg_freight_cost: null })]}
      />,
    );
    expect(screen.queryByText('$0')).toBeNull();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('calls out the worst performer', () => {
    render(
      <DimensionTable
        title="Carrier performance"
        hint="hint"
        label="Carrier"
        rows={[row({ label: 'SlowFreight', late_pct: 60 }), row({ label: 'DHL' })]}
      />,
    );
    expect(screen.getByText(/SlowFreight is the worst performer/)).toBeInTheDocument();
  });
});

describe('CostPanel', () => {
  const cost = {
    coverage_pct: 100,
    total_freight_cost: 50000,
    avg_freight_cost: 125,
    freight_per_unit: 2.5,
    freight_per_kg: null,
    freight_pct_of_goods: 12.5,
    total_landed_cost: 450000,
    freight_spent_on_late_shipments: 18000,
  };

  it('renders nothing without cost data', () => {
    const { container } = render(<CostPanel cost={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('omits only the stats that are missing', () => {
    render(<CostPanel cost={cost} />);
    expect(screen.getByText('Per unit')).toBeInTheDocument();
    // freight_per_kg is null because the file had no weights.
    expect(screen.queryByText('Per kg')).toBeNull();
  });

  it('warns when the figures cover only part of the file', () => {
    render(<CostPanel cost={{ ...cost, coverage_pct: 62 }} />);
    expect(screen.getByText(/62% of rows/)).toBeInTheDocument();
  });

  it('stays quiet about coverage at full coverage', () => {
    render(<CostPanel cost={cost} />);
    expect(screen.queryByText(/of rows that carried/)).toBeNull();
  });
});

describe('QualityPanel', () => {
  it('renders nothing when the file reported no quality data', () => {
    const { container } = render(<QualityPanel quality={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows only the quality metrics the file supported', () => {
    render(
      <QualityPanel
        quality={{
          damage_rate_pct: 3.2,
          damaged_count: 12,
          return_rate_pct: null,
          returned_count: null,
          avg_fill_rate_pct: null,
          perfect_order_rate_pct: 88.5,
          coverage_pct: 100,
        }}
      />,
    );
    expect(screen.getByText('Damage rate')).toBeInTheDocument();
    expect(screen.queryByText('Return rate')).toBeNull();
    expect(screen.queryByText('Avg fill rate')).toBeNull();
  });
});

describe('EmissionsPanel', () => {
  it('renders nothing without emissions data', () => {
    const { container } = render(<EmissionsPanel emissions={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('breaks the footprint down by mode and flags it as an estimate', () => {
    render(
      <EmissionsPanel
        emissions={{
          coverage_pct: 100,
          total_co2_kg: 12500,
          avg_co2_per_shipment_kg: 31.2,
          co2_by_mode_kg: { air: 10000, ocean: 2500 },
        }}
      />,
    );
    expect(screen.getByText('air')).toBeInTheDocument();
    expect(screen.getByText(/indicative, not a certified carbon calculation/)).toBeInTheDocument();
  });
});
