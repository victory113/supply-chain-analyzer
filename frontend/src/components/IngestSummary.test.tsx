import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { IngestReport } from '@/api/types';

import { IngestSummary } from './IngestSummary';

function report(overrides: Partial<IngestReport> = {}): IngestReport {
  return {
    accepted_rows: 1200,
    rejected_rows: 0,
    derived_delays: 0,
    detected_columns: { vendor: 'Supplier Name', delay_days: 'Days Late' },
    unmapped_columns: [],
    warnings: [],
    ...overrides,
  };
}

describe('IngestSummary', () => {
  it('reports how much of the file was read', () => {
    render(<IngestSummary report={report()} />);
    expect(screen.getByText(/read 1,200 rows/i)).toBeInTheDocument();
    expect(screen.getByText(/recognised 2 columns/i)).toBeInTheDocument();
  });

  it('says so when the delay was calculated rather than supplied', () => {
    // The whole point: a derived number must never look like a given one.
    render(<IngestSummary report={report({ derived_delays: 843 })} />);
    expect(screen.getByText(/calculated from the scheduled and actual dates/i)).toBeInTheDocument();
    expect(screen.getByText(/843/)).toBeInTheDocument();
  });

  it('stays quiet about derivation when the file had a delay column', () => {
    render(<IngestSummary report={report()} />);
    expect(screen.queryByText(/calculated from/i)).toBeNull();
  });

  it('surfaces parser warnings', () => {
    render(<IngestSummary report={report({ warnings: ['Row cap reached; truncated.'] })} />);
    expect(screen.getByText(/row cap reached/i)).toBeInTheDocument();
  });

  it('shows the column mapping on request, including ignored columns', async () => {
    const user = userEvent.setup();
    render(<IngestSummary report={report({ unmapped_columns: ['Internal Notes'] })} />);

    expect(screen.queryByText('Supplier Name')).toBeNull();
    await user.click(screen.getByRole('button', { name: /show column mapping/i }));

    expect(screen.getByText('Supplier Name')).toBeInTheDocument();
    expect(screen.getByText(/ignored: internal notes/i)).toBeInTheDocument();
  });
});
