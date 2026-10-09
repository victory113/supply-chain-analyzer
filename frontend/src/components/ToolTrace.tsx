import { useState } from 'react';

import type { ChatToolCall } from '@/api/types';

/** Tool name -> what it did, in words a non-engineer reads. */
const LABELS: Record<string, string> = {
  list_datasets: 'Listed your datasets',
  get_kpis: 'Read the headline metrics',
  get_vendor_scores: 'Looked up vendor scores',
  get_country_risk: 'Looked up country risk',
  get_trend: 'Read the monthly trend',
  get_risk_breakdown: 'Read the risk breakdown',
  get_dimension: 'Read a performance breakdown',
  get_operations_summary: 'Read cost, quality and carbon',
  get_history: 'Compared across your uploads',
};

interface ToolTraceProps {
  calls: ChatToolCall[];
}

/**
 * The assistant's working, shown as steps.
 *
 * Previously the server decided which metrics to retrieve from keywords in
 * the question, so there was nothing to show — the answer either used the
 * right data or it didn't, invisibly. Now the model picks its own tools, and
 * that choice is the most useful thing a user can audit: it tells them what
 * the answer is actually built on, and makes a wrong assumption visible
 * instead of silent.
 */
export function ToolTrace({ calls }: ToolTraceProps) {
  const [open, setOpen] = useState(false);

  if (calls.length === 0) return null;

  const failed = calls.filter((call) => !call.ok).length;

  return (
    <div className="tool-trace">
      <button
        type="button"
        className="tool-trace-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="tool-trace-caret" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        {calls.length} step{calls.length === 1 ? '' : 's'} taken
        {failed > 0 && <span className="tool-trace-failed"> · {failed} retried</span>}
      </button>

      {open && (
        <ol className="tool-trace-list">
          {calls.map((call, index) => (
            <li key={`${call.name}-${index}`} className={call.ok ? '' : 'is-failed'}>
              <span className="tool-trace-n">{index + 1}</span>
              <span className="tool-trace-body">
                <span className="tool-trace-name">{LABELS[call.name] ?? call.name}</span>
                {call.arguments.dataset && (
                  <span className="tool-trace-arg"> · {call.arguments.dataset}</span>
                )}
                {call.arguments.dimension && (
                  <span className="tool-trace-arg"> · {call.arguments.dimension}</span>
                )}
                {call.summary && <span className="tool-trace-summary">{call.summary}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
