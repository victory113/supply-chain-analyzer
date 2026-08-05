import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { AnalysisProgress } from '@/hooks/useAnalysisStatus';

import { AnalysisProgressBanner } from './AnalysisProgress';

function progress(overrides: Partial<AnalysisProgress> = {}): AnalysisProgress {
  return {
    status: 'running',
    isPending: true,
    isComplete: false,
    isFailed: false,
    timedOut: false,
    errorMessage: null,
    ...overrides,
  };
}

describe('AnalysisProgressBanner', () => {
  it('shows the stage while the analysis is running', () => {
    render(<AnalysisProgressBanner progress={progress()} />);
    expect(screen.getByRole('status')).toHaveTextContent(/analysing/i);
  });

  it('disappears once the analysis completes', () => {
    const { container } = render(
      <AnalysisProgressBanner
        progress={progress({ status: 'completed', isPending: false, isComplete: true })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('says the metrics survived when the model call failed', () => {
    render(
      <AnalysisProgressBanner
        progress={progress({
          status: 'failed',
          isPending: false,
          isFailed: true,
          errorMessage: 'The analysis model returned an error (401).',
        })}
      />,
    );

    const banner = screen.getByRole('status');
    expect(banner).toHaveTextContent(/AI summary could not be generated/i);
    expect(banner).toHaveTextContent(/401/);
    expect(banner).toHaveTextContent(/metrics below are unaffected/i);
  });

  it('does not sit on "Starting…" for an analysis that already finished', () => {
    // Loading the page for a finished analysis skips polling, so the hook has
    // no query data. Before this, the banner fell through to the spinner and
    // claimed the job was starting — forever.
    render(
      <AnalysisProgressBanner
        progress={progress({ status: 'failed', isPending: false, isFailed: true })}
      />,
    );
    expect(screen.queryByText(/starting/i)).toBeNull();
  });
});
