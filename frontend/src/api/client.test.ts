import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  getToken,
  request,
  setColdStartHandler,
  setToken,
  setUnauthorizedHandler,
} from './client';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** What a platform edge returns while the container boots: no error envelope. */
function gatewayResponse(status = 503): Response {
  return new Response('', { status });
}

describe('request', () => {
  beforeEach(() => {
    setToken(null);
    setUnauthorizedHandler(null);
  });

  it('prefixes the API version and returns the parsed body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(request<{ ok: boolean }>('/health')).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health', expect.anything());
  });

  it('attaches the bearer token when one is stored', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);
    setToken('token-123');

    await request('/auth/me');

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer token-123');
  });

  it('omits the token on anonymous requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);
    setToken('token-123');

    await request('/auth/login', { method: 'POST', body: {}, anonymous: true });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('unwraps the backend error envelope into an ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { error: { code: 'conflict', message: 'Email already exists.' } },
          409,
        ),
      ),
    );

    await expect(request('/auth/register')).rejects.toMatchObject({
      status: 409,
      code: 'conflict',
      message: 'Email already exists.',
    });
  });

  it('keeps our own 503 distinct from the platform\'s', async () => {
    // A 503 carrying the error envelope came from the app (the model was
    // unavailable), so it is a real failure and must not be retried away.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { error: { code: 'upstream_error', message: 'Model unavailable' } },
          503,
        ),
      ),
    );

    const error = await request('/analyses').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isUpstreamError).toBe(true);
    expect((error as ApiError).isColdStart).toBe(false);
    expect((error as ApiError).message).toBe('Model unavailable');
  });

  it('clears the stored token and notifies on 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { code: 'authentication_error', message: 'Nope' } }, 401),
      ),
    );
    setToken('stale-token');
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);

    await expect(request('/auth/me')).rejects.toBeInstanceOf(ApiError);

    // A dead credential must not be resent on the next request.
    expect(getToken()).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it('surfaces a network failure as a typed error, not a raw TypeError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    const error = await request('/health').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe('network_error');
  });

  it('returns undefined for a 204 rather than trying to parse an empty body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(request('/uploads/abc')).resolves.toBeUndefined();
  });

  it('does not send a JSON content-type for multipart uploads', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    const formData = new FormData();
    formData.append('file', new File(['a,b'], 'x.csv', { type: 'text/csv' }));
    await request('/uploads', { method: 'POST', formData });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    // The browser must set the multipart boundary itself.
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });
});

describe('cold starts', () => {
  // The API sleeps on the free tier. While it boots, the platform edge answers
  // with a bare 502/503/504 and the request never reaches the app — so these
  // are safe to retry, and the user should be told what's happening rather
  // than shown "Request failed with status 503".
  beforeEach(() => {
    setToken(null);
    setColdStartHandler(null);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    setColdStartHandler(null);
  });

  it('retries an envelope-less gateway error until the server wakes', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(gatewayResponse(503))
      .mockResolvedValueOnce(gatewayResponse(503))
      .mockResolvedValue(jsonResponse({ status: 'ok' }));
    vi.stubGlobal('fetch', fetchMock);

    const promise = request<{ status: string }>('/health');
    await vi.runAllTimersAsync();

    await expect(promise).resolves.toEqual({ status: 'ok' });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('tells the UI while it is waiting, and again when it recovers', async () => {
    const onColdStart = vi.fn();
    setColdStartHandler(onColdStart);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(gatewayResponse()).mockResolvedValue(jsonResponse({})),
    );

    const promise = request('/health');
    await vi.runAllTimersAsync();
    await promise;

    expect(onColdStart).toHaveBeenNthCalledWith(1, true);
    expect(onColdStart).toHaveBeenNthCalledWith(2, false);
  });

  it('gives up with an explanation instead of a raw status code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(gatewayResponse(503)));

    const promise = request('/health').catch((caught: unknown) => caught);
    await vi.runAllTimersAsync();
    const error = await promise;

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isColdStart).toBe(true);
    expect((error as ApiError).message).toMatch(/starting up/i);
    expect((error as ApiError).message).not.toMatch(/status 503/);
  });

  it('does not retry a real application error', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ error: { code: 'authentication_error', message: 'Nope' } }, 401),
    );
    vi.stubGlobal('fetch', fetchMock);

    const promise = request('/auth/me').catch((caught: unknown) => caught);
    await vi.runAllTimersAsync();
    await promise;

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('retries an upload, because a gateway error means nothing was processed', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(gatewayResponse(502))
      .mockResolvedValue(jsonResponse({ upload: { id: 'u1' } }));
    vi.stubGlobal('fetch', fetchMock);

    const formData = new FormData();
    formData.append('file', new File(['a,b'], 'x.csv', { type: 'text/csv' }));

    const promise = request('/uploads', { method: 'POST', formData });
    await vi.runAllTimersAsync();

    await expect(promise).resolves.toEqual({ upload: { id: 'u1' } });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('token storage', () => {
  it('round-trips through localStorage', () => {
    setToken('abc');
    expect(getToken()).toBe('abc');
    setToken(null);
    expect(getToken()).toBeNull();
  });
});
