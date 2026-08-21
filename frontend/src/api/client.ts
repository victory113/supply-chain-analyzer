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

  /** The platform returned a gateway error — our app never saw the request. */
  get isColdStart(): boolean {
    return this.code === 'cold_start';
  }
}

// ── Cold starts ───────────────────────────────────────────────────────
// The API runs on a free tier that sleeps after ~15 minutes idle and takes
// 30-60s to wake. During that window the platform's edge answers with a bare
// 502/503/504 and the request never reaches the app at all — which is exactly
// why retrying is safe here even for POST: nothing was processed.
//
// The distinction that makes this work: our own 503s carry the JSON error
// envelope, the platform's do not. Only the envelope-less ones are retried.

const GATEWAY_STATUSES = new Set([502, 503, 504]);
const RETRY_DELAYS_MS = [2_000, 4_000, 8_000, 12_000, 16_000];

/** Notified when a request is waiting on a sleeping server, so the UI can say so. */
type ColdStartHandler = (waking: boolean) => void;
let onColdStart: ColdStartHandler | null = null;

export function setColdStartHandler(handler: ColdStartHandler | null): void {
  onColdStart = handler;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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
  let hadEnvelope = false;

  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error) {
      hadEnvelope = true;
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details;
    }
  } catch {
    // Non-JSON error body (proxy timeout, HTML error page) — keep the default.
  }

  // No envelope on a gateway status means the platform answered, not us.
  if (!hadEnvelope && GATEWAY_STATUSES.has(response.status)) {
    return new ApiError(
      response.status,
      'cold_start',
      'The server is starting up — this can take up to a minute on the free tier. Please try again in a moment.',
    );
  }

  return new ApiError(response.status, code, message, details);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let waking = false;

  for (let attempt = 0; ; attempt++) {
    try {
      const result = await attemptRequest<T>(path, options);
      if (waking) onColdStart?.(false);
      return result;
    } catch (error) {
      const retryable =
        error instanceof ApiError && error.isColdStart && attempt < RETRY_DELAYS_MS.length;

      if (!retryable) {
        if (waking) onColdStart?.(false);
        throw error;
      }

      if (!waking) {
        waking = true;
        onColdStart?.(true);
      }
      await sleep(RETRY_DELAYS_MS[attempt] ?? 16_000);
    }
  }
}

async function attemptRequest<T>(path: string, options: RequestOptions): Promise<T> {
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
