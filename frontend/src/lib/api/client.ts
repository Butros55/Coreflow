/**
 * HTTP client for the Coreflow API.
 *
 * Auth is a session cookie set by the backend — there is no token in JS, so
 * every request must send credentials and echo the CSRF token on writes.
 * See `apps/accounts/authentication.py` for the server side of this contract.
 */

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? process.env.INTERNAL_API_URL ?? 'http://localhost:8000';

export const API_BASE = `${API_URL}/api/v1`;

const CSRF_COOKIE = 'coreflow_csrftoken';
const CSRF_HEADER = 'X-CSRFToken';
const WORKSPACE_HEADER = 'X-Workspace-ID';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** The error envelope every backend error uses (see apps/core/exceptions.py). */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id?: string;
    detail?: Record<string, string[] | string>;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | undefined;
  /** Field-level validation errors, keyed by field name. */
  readonly fieldErrors: Record<string, string[]>;

  constructor(status: number, body: Partial<ApiErrorBody>, fallbackMessage: string) {
    const error = body?.error;
    super(error?.message ?? fallbackMessage);
    this.name = 'ApiError';
    this.status = status;
    this.code = error?.code ?? 'unknown_error';
    this.requestId = error?.request_id;
    this.fieldErrors = normaliseFieldErrors(error?.detail);
  }

  /** True when the user is not logged in — the SPA should redirect to /login. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** True when logged in but lacking rights. Distinct from unauthenticated. */
  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isValidationError(): boolean {
    return this.status === 400 && Object.keys(this.fieldErrors).length > 0;
  }
}

function normaliseFieldErrors(
  detail: Record<string, string[] | string> | undefined,
): Record<string, string[]> {
  if (!detail) return {};
  return Object.fromEntries(
    Object.entries(detail).map(([field, messages]) => [
      field,
      Array.isArray(messages) ? messages : [String(messages)],
    ]),
  );
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(^|;\\s*)${name}=([^;]*)`));
  return match?.[2] ? decodeURIComponent(match[2]) : null;
}

/**
 * The active workspace id.
 *
 * Held in a module variable rather than React state so that non-component
 * callers (the query client, retry logic) can read it without prop drilling.
 * The server still validates it against the caller's memberships on every
 * request — this is a routing hint, never a grant of access.
 */
let activeWorkspaceId: string | null = null;

export function setActiveWorkspaceId(id: string | null): void {
  activeWorkspaceId = id;
  if (typeof window !== 'undefined') {
    if (id) window.localStorage.setItem('coreflow.workspace', id);
    else window.localStorage.removeItem('coreflow.workspace');
  }
}

export function getActiveWorkspaceId(): string | null {
  if (activeWorkspaceId) return activeWorkspaceId;
  if (typeof window !== 'undefined') {
    activeWorkspaceId = window.localStorage.getItem('coreflow.workspace');
  }
  return activeWorkspaceId;
}

/**
 * Django only sets the CSRF cookie once something calls `get_token()`. On a
 * cold load the SPA may not have it yet, so the first unsafe request bootstraps
 * it. Cached as a promise so N parallel writes trigger one fetch, not N.
 */
let csrfBootstrap: Promise<void> | null = null;

async function ensureCsrfToken(): Promise<void> {
  if (readCookie(CSRF_COOKIE)) return;
  csrfBootstrap ??= fetch(`${API_BASE}/auth/csrf`, { credentials: 'include' })
    .then(() => undefined)
    .finally(() => {
      csrfBootstrap = null;
    });
  await csrfBootstrap;
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  /** Skip the workspace header (for endpoints that are not workspace-scoped). */
  skipWorkspace?: boolean;
  query?: Record<string, string | number | boolean | undefined | null>;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${API_BASE}${path.startsWith('/') ? path : `/${path}`}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, skipWorkspace, query, headers: extraHeaders, ...rest } = options;
  const method = (rest.method ?? 'GET').toUpperCase();

  const headers = new Headers(extraHeaders);
  headers.set('Accept', 'application/json');

  if (body !== undefined && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  if (UNSAFE_METHODS.has(method)) {
    await ensureCsrfToken();
    const token = readCookie(CSRF_COOKIE);
    if (token) headers.set(CSRF_HEADER, token);
  }

  if (!skipWorkspace) {
    const workspaceId = getActiveWorkspaceId();
    if (workspaceId) headers.set(WORKSPACE_HEADER, workspaceId);
  }

  const response = await fetch(buildUrl(path, query), {
    ...rest,
    method,
    headers,
    // Required: the session cookie is the credential.
    credentials: 'include',
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.includes('application/json');

  if (!response.ok) {
    // An error page (e.g. a proxy 502) is not JSON; don't let the parse failure
    // mask the real status.
    const errorBody: Partial<ApiErrorBody> = isJson ? await response.json().catch(() => ({})) : {};
    throw new ApiError(response.status, errorBody, `Request failed with status ${response.status}`);
  }

  if (!isJson) {
    return (await response.blob()) as T;
  }

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'PUT', body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'DELETE' }),
};

/** Standard paginated envelope (see apps/core/pagination.py). */
export interface Paginated<T> {
  count: number;
  num_pages: number;
  page: number;
  page_size: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
