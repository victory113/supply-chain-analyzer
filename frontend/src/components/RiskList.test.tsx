import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Risk } from '@/api/types';

import { RiskList } from './RiskList';

function makeRisk(overrides: Partial<Risk> = {}): Risk {
  return {
    id: 'risk-1',
    position: 1,
    title: 'Vendor concentration',
    risk_level: 'HIGH',
    explanation: 'One vendor carries most of the late volume.',
    recommendation: 'Qualify a second supplier this quarter.',
    affected_items: ['GlobalParts Co'],
    evidence_metric: 'vendors[0].health_score',
    ...overrides,
  };
}

describe('RiskList', () => {
  it('renders the title, explanation and recommendation', () => {
    render(<RiskList risks={[makeRisk()]} />);

    expect(screen.getByText('Vendor concentration')).toBeInTheDocument();
    expect(
      screen.getByText('One vendor carries most of the late volume.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Qualify a second supplier this quarter\./),
    ).toBeInTheDocument();
  });

  it('shows which computed metric the risk is grounded in', () => {
    // The traceability link is the whole point of the evidence_metric field —
    // if it stops rendering, recommendations become unverifiable claims.
    render(<RiskList risks={[makeRisk()]} />);
    expect(screen.getByText(/vendors\[0\]\.health_score/)).toBeInTheDocument();
  });

  it('renders each affected item as its own chip', () => {
    render(
      <RiskList risks={[makeRisk({ affected_items: ['Acme', 'Beta', 'Gamma'] })]} />,
    );
    expect(screen.getByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByText('Gamma')).toBeInTheDocument();
  });

  it('colour-codes by risk level', () => {
    const { container } = render(
      <RiskList risks={[makeRisk({ risk_level: 'MEDIUM' })]} />,
    );
    expect(container.querySelector('.risk-item.medium')).not.toBeNull();
  });

  it('omits optional sections rather than rendering empty ones', () => {
    render(
      <RiskList
        risks={[
          makeRisk({ recommendation: null, evidence_metric: null, affected_items: [] }),
        ]}
      />,
    );
    expect(screen.queryByText(/Do this:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/grounded in/)).not.toBeInTheDocument();
  });

  it('explains itself when there are no risks', () => {
    render(<RiskList risks={[]} />);
    expect(screen.getByText(/No risks were identified/)).toBeInTheDocument();
  });
});
