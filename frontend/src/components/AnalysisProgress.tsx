import type { AnalysisProgress as Progress } from '@/hooks/useAnalysisStatus';

const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued — waiting for a worker',
  running: 'Analysing — computing metrics and writing the summary',
  completed: 'Analysis complete',
  failed: 'Analysis failed',
};

/**
 * Progress banner for a queued analysis.
 *
 * The key message when the AI step fails: the computed metrics are already
 * saved and the dashboard below is still accurate. Users otherwise assume a
 * red banner means the whole upload is worthless.
 */
export function AnalysisProgressBanner({ progress }: { progress: Progress }) {
  if (progress.isComplete) return null;

  if (progress.timedOut) {
    return (
      <div className="alert alert-warning" role="status">
        This analysis is taking longer than expected. The computed metrics below are
        already saved — refresh in a moment, or re-run the analysis.
      </div>
    );
  }

  if (progress.isFailed) {
    return (
      <div className="alert alert-warning" role="status">
        <strong>The AI summary could not be generated.</strong>{' '}
        {progress.errorMessage ?? 'The analysis model was unavailable.'} All computed
        metrics below are unaffected — they are calculated without the model.
      </div>
    );
  }

  const label = progress.status ? STAGE_LABELS[progress.status] : 'Starting…';

  return (
    <div className="card" role="status" aria-live="polite">
      <div className="row-between" style={{ marginBottom: 10 }}>
        <span className="small">{label}</span>
        <span className="tiny faint">this usually takes 10–30 seconds</span>
      </div>
      <div className="progress-track">
        <div className="progress-bar indeterminate" />
      </div>
    </div>
  );
}
