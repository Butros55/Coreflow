import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type Paginated } from '@/lib/api/client';
import type { Membership, Workspace } from '@/lib/api/types';

// ---------------------------------------------------------------------------
// Workspace / company profile (reuses the workspaces endpoint)
// ---------------------------------------------------------------------------

export function useUpdateWorkspace(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Workspace>) =>
      api.patch<Workspace>(`/workspaces/${workspaceId}/`, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session'] }),
  });
}

// ---------------------------------------------------------------------------
// Service types
// ---------------------------------------------------------------------------

export interface ServiceType {
  id: string;
  name: string;
  description: string;
  default_hourly_rate: string | null;
  default_invoice_text: string;
  active: boolean;
}

export function useServiceTypesAll() {
  return useQuery({
    queryKey: ['service-types', 'all'],
    queryFn: () =>
      api.get<Paginated<ServiceType>>('/service-types/', { query: { page_size: 100 } }),
  });
}

export function useSaveServiceType() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<ServiceType> & { id?: string }) =>
      payload.id
        ? api.patch<ServiceType>(`/service-types/${payload.id}/`, payload)
        : api.post<ServiceType>('/service-types/', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['service-types'] }),
  });
}

export function useDeleteServiceType() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/service-types/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['service-types'] }),
  });
}

// ---------------------------------------------------------------------------
// Team
// ---------------------------------------------------------------------------

export function useMembers(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ['members', workspaceId],
    queryFn: () => api.get<Membership[]>(`/workspaces/${workspaceId}/members/`),
    enabled: Boolean(workspaceId),
  });
}

// ---------------------------------------------------------------------------
// Integration centre
// ---------------------------------------------------------------------------

export interface IntegrationProfile {
  company_name: string;
  organization_id: string;
  tax_type: string;
  small_business: boolean;
  subscription_status: string;
  fetched_at: string | null;
}

export interface IntegrationStatus {
  provider: 'lexware' | 'clockodo';
  enabled: boolean;
  configured: boolean;
  webhook_configured: boolean;
  connected: boolean;
  profile: IntegrationProfile | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_failure_summary: string;
  open_conflicts: number;
  linked_objects: number;
  webhook_events: number;
  /** Clockodo only: the URL to paste into Clockodo's webhook settings. */
  webhook_url?: string;
  /** Clockodo only: handshake secret received on webhook creation. */
  webhook_handshake_secret?: string;
}

export function useIntegrationStatus() {
  return useQuery({
    queryKey: ['integration-status'],
    queryFn: () =>
      api.get<{ lexware: IntegrationStatus; clockodo: IntegrationStatus }>('/integrations/status'),
    refetchInterval: 30_000,
  });
}

export function useTestConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (provider: 'lexware' | 'clockodo') =>
      api.post<{ ok: boolean; company_name: string }>(`/integrations/${provider}/test`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['integration-status'] }),
  });
}

export function useTriggerSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (provider: 'lexware' | 'clockodo') =>
      api.post<{ ok: boolean; queued: boolean }>(`/integrations/${provider}/sync`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integration-status'] });
      queryClient.invalidateQueries({ queryKey: ['sync-conflicts'] });
    },
  });
}

export interface SyncConflict {
  id: string;
  provider: string;
  resource_type: string;
  reason: string;
  local_snapshot: Record<string, unknown>;
  remote_snapshot: Record<string, unknown>;
  detected_at: string;
  resolution_status: string;
  external_id: string;
}

export function useSyncConflicts() {
  return useQuery({
    queryKey: ['sync-conflicts'],
    queryFn: () => api.get<Paginated<SyncConflict>>('/sync-conflicts/'),
  });
}

export function useResolveConflict() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, resolution }: { id: string; resolution: 'local' | 'remote' | 'ignore' }) =>
      api.post<{ ok: boolean }>(`/sync-conflicts/${id}/resolve/`, { resolution }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-conflicts'] });
      queryClient.invalidateQueries({ queryKey: ['integration-status'] });
    },
  });
}
