import { API_BASE } from '@/lib/api/client';

export interface ReadinessResponse {
  status: 'ok' | 'degraded';
  checks: {
    database: { status: string; latency_ms?: number; error?: string };
    cache: { status: string; latency_ms?: number; error?: string };
    integrations: { lexware: 'enabled' | 'disabled'; clockify: 'enabled' | 'disabled' };
  };
}

export interface VersionResponse {
  service: string;
  version: string;
  environment: string;
  time_zone: string;
}

// The probes live at the API root, not under /api/v1, so they bypass the
// versioned client and are fetched directly.
const ROOT = API_BASE.replace(/\/api\/v1$/, '');

export const systemApi = {
  readiness: async (): Promise<ReadinessResponse> => {
    const response = await fetch(`${ROOT}/readyz`, { credentials: 'include' });
    // 503 is a valid, meaningful answer here ("degraded"), not an error to throw
    // on — the dashboard wants to render it.
    return (await response.json()) as ReadinessResponse;
  },
  version: async (): Promise<VersionResponse> => {
    const response = await fetch(`${ROOT}/version`, { credentials: 'include' });
    if (!response.ok) throw new Error(`Version check failed: ${response.status}`);
    return (await response.json()) as VersionResponse;
  },
};
