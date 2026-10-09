import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { ChatToolCall } from '@/api/types';

import { ToolTrace } from './ToolTrace';

function call(overrides: Partial<ChatToolCall> = {}): ChatToolCall {
  return {
    name: 'get_vendor_scores',
    arguments: { dataset: 'q1.csv' },
    ok: true,
    summary: '5 vendor(s)',
    ...overrides,
  };
}

describe('ToolTrace', () => {
  it('renders nothing when the model called no tools', () => {
    const { container } = render(<ToolTrace calls={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('summarises how many steps were taken', () => {
    render(<ToolTrace calls={[call(), call({ name: 'get_trend' })]} />);
    expect(screen.getByRole('button', { name: /2 steps taken/i })).toBeInTheDocument();
  });

  it('uses the singular for a single step', () => {
    render(<ToolTrace calls={[call()]} />);
    expect(screen.getByRole('button', { name: /1 step taken/i })).toBeInTheDocument();
  });

  it('keeps the detail collapsed until asked for', () => {
    render(<ToolTrace calls={[call()]} />);
    expect(screen.queryByText(/Looked up vendor scores/)).toBeNull();
  });

  it('shows each step in plain English, in order', async () => {
    const user = userEvent.setup();
    render(
      <ToolTrace
        calls={[
          call({ name: 'list_datasets', arguments: {}, summary: '2 dataset(s)' }),
          call({ name: 'get_vendor_scores' }),
          call({ name: 'get_trend', summary: 'worsening, 12 month(s)' }),
        ]}
      />,
    );

    await user.click(screen.getByRole('button', { name: /3 steps taken/i }));

    const steps = screen.getAllByRole('listitem').map((li) => li.textContent ?? '');
    expect(steps[0]).toContain('Listed your datasets');
    expect(steps[1]).toContain('Looked up vendor scores');
    expect(steps[2]).toContain('Read the monthly trend');
  });

  it('shows which dataset a step read', async () => {
    const user = userEvent.setup();
    render(<ToolTrace calls={[call({ arguments: { dataset: 'march.csv' } })]} />);

    await user.click(screen.getByRole('button'));

    expect(screen.getByText(/march\.csv/)).toBeInTheDocument();
  });

  it('flags a failed step rather than hiding it', async () => {
    // A retried lookup is information: it shows the model corrected itself.
    const user = userEvent.setup();
    render(
      <ToolTrace
        calls={[
          call({ ok: false, summary: "No dataset named 'q9'." }),
          call({ summary: '5 vendor(s)' }),
        ]}
      />,
    );

    expect(screen.getByRole('button', { name: /1 retried/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button'));
    expect(screen.getAllByRole('listitem')[0]).toHaveClass('is-failed');
  });

  it('falls back to the raw tool name if one is unrecognised', async () => {
    const user = userEvent.setup();
    render(<ToolTrace calls={[call({ name: 'get_future_tool' })]} />);

    await user.click(screen.getByRole('button'));

    expect(screen.getByText('get_future_tool')).toBeInTheDocument();
  });
});
