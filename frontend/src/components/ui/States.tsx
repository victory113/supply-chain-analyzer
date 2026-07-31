import type { ReactNode } from 'react';

import { ApiError } from '@/api/client';

import { Spinner } from './Spinner';

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state">
      <div className="row" style={{ justifyContent: 'center' }}>
        <Spinner size="lg" label={label} />
      </div>
    </div>
  );
}

interface EmptyStateProps {
  icon?: string;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ icon = '📭', title, body, action }: EmptyStateProps) {
  return (
    <div className="state">
      <div className="state-icon" aria-hidden="true">
        {icon}
      </div>
      <div className="state-title">{title}</div>
      {body && <div className="state-body">{body}</div>}
      {action}
    </div>
  );
}

/**
 * Turns an unknown thrown value into something a user can act on.
 *
 * Auth errors are handled globally by the client, so they're not surfaced here
 * — by the time this renders, the app has already redirected to login.
 */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  let title = 'Something went wrong';
  let body = 'An unexpected error occurred. Please try again.';

  if (error instanceof ApiError) {
    body = error.message;
    if (error.isNotFound) title = 'Not found';
    else if (error.isUpstreamError) title = 'Service unavailable';
    else if (error.code === 'network_error') title = 'Connection problem';
    else if (error.status === 422) title = "That didn't validate";
  } else if (error instanceof Error) {
    body = error.message;
  }

  return (
    <div className="state">
      <div className="state-icon" aria-hidden="true">
        ⚠️
      </div>
      <div className="state-title">{title}</div>
      <div className="state-body">{body}</div>
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof ApiError || error instanceof Error
      ? error.message
      : 'Something went wrong.';
  return (
    <div className="alert alert-error" role="alert">
      {message}
    </div>
  );
}
