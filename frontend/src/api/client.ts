/**
 * HTTP client.
 *
 * One place that knows about base URLs, auth headers, and the backend's error
 * envelope. Everything above this layer works with typed objects and
 * `ApiError`, never with `Response`.
 */

import type { ApiErrorBody } from './types';

/**
 * Relative by default so the Vite dev proxy (local) and the Netlify redirect
 * (production) can forward `/api` to the backend on the same origin — which
 * means no CORS preflight and no cross-origin cookie problems.
 */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';
const API_PREFIX = '/api/v1';

const TOKEN_KEY = 'sca.access_token';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** 502/503 from our own upstream-error taxonomy — the model or a dependency. */
  get isUpstreamError(): boolean {
    return this.status === 502 || this.status === 503;
  }
}

// ── Token storage ─────────────────────────────────────────────────────
// localStorage is a deliberate tradeoff: it survives a refresh and keeps the
// backend stateless, at the cost of XSS exposure that an httpOnly cookie would
// avoid. Cookies would require CSRF protection and a shared parent domain,
// neither of which this deployment has.

let inMemoryToken: string | null = null;

export function getToken(): string | null {
  if (inMemoryToken !== null) return inMemoryToken;
  try {
    inMemoryToken = window.localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private browsing modes can throw on localStorage access; fall back to
    // memory-only so the session still works for this tab.
    inMemoryToken = null;
  }
  return inMemoryToken;
}

export function setToken(token: string | null): void {
  inMemoryToken = token;
  try {
    if (token === null) window.localStorage.removeItem(TOKEN_KEY);
    else window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* memory-only session */
  }
}

/** Fires when a request is rejected with 401 so the app can log the user out. */
type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

// ── Request ───────────────────────────────────────────────────────────

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  /** FormData bypasses JSON encoding so the browser sets the multipart boundary. */
  formData?: FormData;
  signal?: AbortSignal;
  /** Skip the Authorization header (registration, login, sample data). */
  anonymous?: boolean;
}

async function parseError(response: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = `Request failed with status ${response.status}`;
  let details: Record<string, unknown> | undefined;

  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details;
    }
  } catch {
    // Non-JSON error body (proxy timeout, HTML error page) — keep the default.
  }

  return new ApiError(response.status, code, message, details);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, formData, signal, anonymous = false } = options;

  const headers: Record<string, string> = {};
  if (!anonymous) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${API_PREFIX}${path}`, {
      method,
      headers,
      body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError(
      0,
      'network_error',
      'Could not reach the server. Check your connection and try again.',
    );
  }

  if (response.status === 401 && !anonymous) {
    // The token is gone or expired — clear it before the error propagates so a
    // retry doesn't resend a credential we already know is dead.
    setToken(null);
    onUnauthorized?.();
  }

  if (!response.ok) throw await parseError(response);

  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown, opts?: Partial<RequestOptions>) =>
    request<T>(path, { method: 'POST', body, ...opts }),
  postForm: <T>(path: string, formData: FormData) =>
    request<T>(path, { method: 'POST', formData }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
