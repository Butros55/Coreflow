'use client';

import { useQuery } from '@tanstack/react-query';

import { api, type Paginated } from '@/lib/api/client';

export interface AuditLogEntry {
  id: string;
  created_at: string;
  action: string;
  actor_email: string;
  target_type: string;
  target_id: string;
  summary: string;
  metadata: Record<string, unknown>;
  ip_address: string | null;
}

export interface AuditLogParams {
  action?: string;
  page?: number;
}

export function useAuditLog(params: AuditLogParams = {}) {
  return useQuery({
    queryKey: ['audit-log', params],
    queryFn: () =>
      api.get<Paginated<AuditLogEntry>>('/audit-log/', {
        query: { ...params, page_size: 100 },
      }),
  });
}
