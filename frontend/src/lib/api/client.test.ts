import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiFetch, getActiveWorkspaceId, setActiveWorkspaceId } from '@/lib/api/client';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** Await a call expected to reject, returning the ApiError it threw. */
async function expectApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw new Error(`Expected an ApiError, got: ${String(error)}`);
  }
  throw new Error('Expected the request to reject, but it resolved.');
}

describe('apiFetch', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    setActiveWorkspaceId(null);
    document.cookie = 'coreflow_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('always sends credentials — the session cookie is the credential', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await apiFetch('/thing');
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: 'include' });
  });

  it('does not send a CSRF token on safe methods', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await apiFetch('/thing');
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.has('X-CSRFToken')).toBe(false);
  });

  it('sends the CSRF token from the cookie on unsafe methods', async () => {
    document.cookie = 'coreflow_csrftoken=tok123; path=/';
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiFetch('/thing', { method: 'POST', body: { a: 1 } });

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get('X-CSRFToken')).toBe('tok123');
  });

  it('bootstraps the CSRF cookie before an unsafe request when it is missing', async () => {
    // Django only sets the cookie once something calls get_token(), so a cold
    // load must fetch it first or the POST is rejected.
    fetchMock.mockImplementation((url: string) => {
      if (String(url).endsWith('/auth/csrf')) {
        document.cookie = 'coreflow_csrftoken=bootstrapped; path=/';
        return Promise.resolve(jsonResponse({ csrf_token: 'bootstrapped' }));
      }
      return Promise.resolve(jsonResponse({ ok: true }));
    });

    await apiFetch('/thing', { method: 'POST', body: {} });

    expect(fetchMock.mock.calls[0]?.[0]).toContain('/auth/csrf');
    const headers = fetchMock.mock.calls[1]?.[1]?.headers as Headers;
    expect(headers.get('X-CSRFToken')).toBe('bootstrapped');
  });

  it('sends the workspace header when one is active', async () => {
    setActiveWorkspaceId('ws-1');
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiFetch('/thing');

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get('X-Workspace-ID')).toBe('ws-1');
  });

  it('omits the workspace header when skipWorkspace is set', async () => {
    setActiveWorkspaceId('ws-1');
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiFetch('/auth/login', { method: 'POST', body: {}, skipWorkspace: true });

    const headers = fetchMock.mock.calls.at(-1)?.[1]?.headers as Headers;
    expect(headers.has('X-Workspace-ID')).toBe(false);
  });

  it('serialises query params and drops empty ones', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiFetch('/things', { query: { search: 'acme', page: 2, archived: undefined, q: '' } });

    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain('search=acme');
    expect(url).toContain('page=2');
    expect(url).not.toContain('archived');
    expect(url).not.toContain('q=');
  });

  it('returns undefined for 204 rather than trying to parse a body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiFetch('/thing', { method: 'DELETE' })).resolves.toBeUndefined();
  });

  it('parses the backend error envelope', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'invalid_credentials',
            message: 'Invalid email address or password.',
            request_id: 'req-1',
          },
        },
        400,
      ),
    );

    await expect(apiFetch('/auth/login', { method: 'POST', body: {} })).rejects.toSatisfy(
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === 'invalid_credentials' &&
        error.status === 400 &&
        error.requestId === 'req-1' &&
        error.message === 'Invalid email address or password.',
    );
  });

  it('exposes field errors from a validation response', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'invalid',
            message: 'Validation failed.',
            detail: { email: ['Enter a valid email.'], name: 'Required.' },
          },
        },
        400,
      ),
    );

    const error = await expectApiError(apiFetch('/clients', { method: 'POST', body: {} }));
    expect(error.isValidationError).toBe(true);
    // A bare string is normalised to an array so callers need one shape.
    expect(error.fieldErrors).toEqual({
      email: ['Enter a valid email.'],
      name: ['Required.'],
    });
  });

  it('distinguishes unauthenticated from forbidden', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: { code: 'x', message: 'y' } }, 401));
    const unauth = await expectApiError(apiFetch('/thing'));
    expect(unauth.isUnauthenticated).toBe(true);
    expect(unauth.isForbidden).toBe(false);

    fetchMock.mockResolvedValue(jsonResponse({ error: { code: 'x', message: 'y' } }, 403));
    const forbidden = await expectApiError(apiFetch('/thing'));
    expect(forbidden.isUnauthenticated).toBe(false);
    expect(forbidden.isForbidden).toBe(true);
  });

  it('does not mask a non-JSON error behind a parse failure', async () => {
    // e.g. an nginx 502 HTML page — the status must still surface.
    fetchMock.mockResolvedValue(
      new Response('<html>Bad Gateway</html>', {
        status: 502,
        headers: { 'content-type': 'text/html' },
      }),
    );

    const error = await expectApiError(apiFetch('/thing'));
    expect(error.status).toBe(502);
    expect(error.code).toBe('unknown_error');
  });
});

describe('active workspace', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setActiveWorkspaceId(null);
  });

  it('persists across reloads', () => {
    setActiveWorkspaceId('ws-42');
    expect(window.localStorage.getItem('coreflow.workspace')).toBe('ws-42');
    expect(getActiveWorkspaceId()).toBe('ws-42');
  });

  it('clears on logout', () => {
    setActiveWorkspaceId('ws-42');
    setActiveWorkspaceId(null);
    expect(window.localStorage.getItem('coreflow.workspace')).toBeNull();
    expect(getActiveWorkspaceId()).toBeNull();
  });
});
