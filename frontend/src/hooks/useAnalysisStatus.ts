import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { analysesApi, queryKeys } from '@/api/endpoints';
import type { AnalysisStatus } from '@/api/types';
import { TERMINAL_ANALYSIS_STATUSES } from '@/api/types';

const POLL_INTERVAL_MS = 2500;
/** ~2 minutes. The backend's Celery soft time limit is 300s, but the analysis
 *  itself is one model call; past this the job is almost certainly wedged. */
const MAX_POLLS = 48;

interface UseAnalysisStatusOptions {
  analysisId: string | null;
  /** Skip polling when the caller already knows the analysis finished. */
  enabled?: boolean;
}

export interface AnalysisProgress {
  status: AnalysisStatus | null;
  isPending: boolean;
  isComplete: boolean;
  isFailed: boolean;
  timedOut: boolean;
  errorMessage: string | null;
}

/**
 * Polls an analysis until it reaches a terminal state.
 *
 * The backend returns 202 from the upload endpoint and does the model call in
 * a worker, so the UI polls a deliberately tiny status payload rather than
 * holding a request open. Polling stops on a terminal status — no interval is
 * left running behind a finished job.
 */
export function useAnalysisStatus({
  analysisId,
  enabled = true,
}: UseAnalysisStatusOptions): AnalysisProgress {
  const query = useQuery({
    queryKey: queryKeys.analysisStatus(analysisId ?? 'none'),
    queryFn: () => analysesApi.status(analysisId as string),
    enabled: enabled && analysisId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && TERMINAL_ANALYSIS_STATUSES.includes(status)) return false;
      if (query.state.dataUpdateCount >= MAX_POLLS) return false;
      return POLL_INTERVAL_MS;
    },
    // A transient 500 mid-poll shouldn't kill the whole progress indicator.
    retry: 2,
  });

  // The query result doesn't expose an update count, so track responses here.
  // `dataUpdatedAt` changes on every successful fetch, including ones that
  // return the same status.
  const [pollCount, setPollCount] = useState(0);
  const { dataUpdatedAt } = query;

  useEffect(() => {
    if (dataUpdatedAt > 0) setPollCount((count) => count + 1);
  }, [dataUpdatedAt]);

  const status = query.data?.status ?? null;
  const isComplete = status === 'completed';
  const isFailed = status === 'failed';
  const isPending = status === 'queued' || status === 'running';

  return {
    status,
    isPending,
    isComplete,
    isFailed,
    // Still not terminal after the poll budget is spent — surface it rather
    // than spinning forever.
    timedOut: isPending && pollCount >= MAX_POLLS,
    errorMessage: query.data?.error_message ?? null,
  };
}
