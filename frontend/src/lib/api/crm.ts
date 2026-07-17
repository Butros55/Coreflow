import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type Paginated } from '@/lib/api/client';
import type { User } from '@/lib/api/types';

export type ClientStatus = 'prospect' | 'active' | 'paused' | 'former';

export interface ClientStats {
  active_projects: number;
  open_seconds: number;
  /** Decimal as string — display only, never arithmetic. */
  open_amount: string;
  last_activity_at: string | null;
}

export interface ClientPrimaryContact {
  id: string;
  full_name: string;
  email: string;
  phone: string;
}

export interface Client {
  id: string;
  name: string;
  short_name: string;
  legal_form: string;
  client_number: string;
  status: ClientStatus;
  industry: string;
  website: string;
  email: string;
  phone: string;
  billing_street: string;
  billing_zip: string;
  billing_city: string;
  billing_country_code: string;
  shipping_street: string;
  shipping_zip: string;
  shipping_city: string;
  shipping_country_code: string;
  tax_number: string;
  vat_id: string;
  default_hourly_rate: string | null;
  payment_term_days: number | null;
  currency: string;
  notes: string;
  tags: string[];
  acquisition_source: string;
  customer_since: string | null;
  archived: boolean;
  primary_contact: ClientPrimaryContact | null;
  stats: ClientStats;
  created_at: string;
  updated_at: string;
}

export interface ClientContact {
  id: string;
  client: string;
  first_name: string;
  last_name: string;
  full_name: string;
  position: string;
  email: string;
  phone: string;
  mobile: string;
  preferred_channel: 'email' | 'phone' | 'mobile' | 'other';
  is_primary: boolean;
  notes: string;
}

export interface ClientNote {
  id: string;
  client: string;
  author: User | null;
  content: string;
  note_type: 'note' | 'call' | 'meeting' | 'email';
  follow_up_at: string | null;
  created_at: string;
}

export interface ClientActivity {
  id: string;
  client: string;
  event_type: string;
  event_type_display: string;
  description: string;
  occurred_at: string;
  actor: User | null;
  project: string | null;
  note: string | null;
}

export interface ClientListParams {
  search?: string;
  status?: ClientStatus | '';
  archived?: boolean;
  ordering?: string;
  page?: number;
}

export const CLIENT_STATUS_LABELS: Record<ClientStatus, string> = {
  prospect: 'Interessent',
  active: 'Aktiv',
  paused: 'Pausiert',
  former: 'Ehemalig',
};

export function useClients(params: ClientListParams = {}) {
  return useQuery({
    queryKey: ['clients', params],
    queryFn: () =>
      api.get<Paginated<Client>>('/clients/', {
        query: {
          search: params.search,
          status: params.status,
          archived: params.archived,
          ordering: params.ordering,
          page: params.page,
          page_size: 100,
        },
      }),
  });
}

export function useClient(id: string | null) {
  return useQuery({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}/`),
    enabled: Boolean(id),
  });
}

export function useCreateClient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Client>) => api.post<Client>('/clients/', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['clients'] }),
  });
}

export function useUpdateClient(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Client>) => api.patch<Client>(`/clients/${id}/`, patch),
    onSuccess: (client) => {
      queryClient.setQueryData(['client', id], client);
      queryClient.invalidateQueries({ queryKey: ['clients'] });
    },
  });
}

export function useClientContacts(clientId: string | null) {
  return useQuery({
    queryKey: ['client-contacts', clientId],
    queryFn: () =>
      api.get<Paginated<ClientContact>>('/client-contacts/', { query: { client: clientId } }),
    enabled: Boolean(clientId),
  });
}

export function useSaveContact(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<ClientContact> & { id?: string }) =>
      payload.id
        ? api.patch<ClientContact>(`/client-contacts/${payload.id}/`, payload)
        : api.post<ClientContact>('/client-contacts/', { ...payload, client: clientId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['client-contacts', clientId] });
      queryClient.invalidateQueries({ queryKey: ['client', clientId] });
      queryClient.invalidateQueries({ queryKey: ['client-activities', clientId] });
    },
  });
}

export function useClientNotes(clientId: string | null) {
  return useQuery({
    queryKey: ['client-notes', clientId],
    queryFn: () =>
      api.get<Paginated<ClientNote>>('/client-notes/', { query: { client: clientId } }),
    enabled: Boolean(clientId),
  });
}

export function useCreateNote(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { content: string; note_type: ClientNote['note_type'] }) =>
      api.post<ClientNote>('/client-notes/', { ...payload, client: clientId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['client-notes', clientId] });
      queryClient.invalidateQueries({ queryKey: ['client-activities', clientId] });
    },
  });
}

export function useClientActivities(clientId: string | null) {
  return useQuery({
    queryKey: ['client-activities', clientId],
    queryFn: () =>
      api.get<Paginated<ClientActivity>>('/client-activities/', { query: { client: clientId } }),
    enabled: Boolean(clientId),
  });
}
