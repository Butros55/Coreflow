import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { API_BASE, api, type Paginated } from '@/lib/api/client';

export type BillingStatus =
  'not_billable' | 'open' | 'marked_for_invoice' | 'invoice_draft_created' | 'billed' | 'cancelled';

export const BILLING_STATUS_LABELS: Record<BillingStatus, string> = {
  not_billable: 'Nicht abrechenbar',
  open: 'Offen',
  marked_for_invoice: 'Vorgemerkt',
  invoice_draft_created: 'Entwurf erstellt',
  billed: 'Abgerechnet',
  cancelled: 'Storniert',
};

export interface ServiceType {
  id: string;
  name: string;
  description: string;
  default_hourly_rate: string | null;
  default_invoice_text: string;
  active: boolean;
}

/** Active invoice this entry is billed on. `source === 'lexware_import'`
 * means the assignment was made by the Lexware import, not the composer. */
export interface TimeEntryInvoiceLink {
  invoice_id: string;
  invoice_number: string;
  source: 'compose' | 'lexware_import';
}

export interface TimeEntry {
  id: string;
  user: string;
  client: string;
  client_name: string;
  project: string | null;
  project_name: string | null;
  phase: string | null;
  task: string | null;
  task_title: string | null;
  service_type: string | null;
  service_type_name: string | null;
  description: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number;
  source: 'manual' | 'timer' | 'clockodo';
  billable: boolean;
  hourly_rate: string;
  computed_amount: string;
  billing_status: BillingStatus;
  rounded_from_seconds: number | null;
  is_running: boolean;
  invoice_link: TimeEntryInvoiceLink | null;
}

export function useServiceTypes() {
  return useQuery({
    queryKey: ['service-types'],
    queryFn: () => api.get<Paginated<ServiceType>>('/service-types/', { query: { active: true } }),
    staleTime: 5 * 60_000,
  });
}

export interface TimeEntryListParams {
  /** ISO datetimes forming the half-open interval [from, to). */
  time_from?: string;
  time_to?: string;
  client?: string;
  project?: string;
  billing_status?: BillingStatus;
}

export function timesheetExportUrl(
  format: 'csv' | 'pdf',
  params: TimeEntryListParams = {},
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(key, String(value));
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : '';
  return `${API_BASE}/time-entries/export.${format}/${suffix}`;
}

export function useTimeEntries(params: TimeEntryListParams) {
  return useQuery({
    queryKey: ['time-entries', params],
    queryFn: () =>
      api.get<Paginated<TimeEntry>>('/time-entries/', {
        query: { ...params, page_size: 200, ordering: '-started_at' },
      }),
  });
}

export interface TimeEntryPayload {
  client?: string;
  project?: string | null;
  task?: string | null;
  service_type?: string | null;
  description?: string;
  started_at?: string;
  ended_at?: string | null;
  duration_input_seconds?: number;
  billable?: boolean;
}

function invalidateTimeWorld(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ['time-entries'] });
  queryClient.invalidateQueries({ queryKey: ['clients'] });
  queryClient.invalidateQueries({ queryKey: ['projects'] });
  queryClient.invalidateQueries({ queryKey: ['tasks'] });
}

export function useCreateTimeEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: TimeEntryPayload) => api.post<TimeEntry>('/time-entries/', payload),
    onSuccess: () => invalidateTimeWorld(queryClient),
  });
}

export function useUpdateTimeEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: TimeEntryPayload & { id: string }) =>
      api.patch<TimeEntry>(`/time-entries/${id}/`, patch),
    onSuccess: () => invalidateTimeWorld(queryClient),
  });
}

export function useDeleteTimeEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/time-entries/${id}/`),
    onSuccess: () => invalidateTimeWorld(queryClient),
  });
}

// ---------------------------------------------------------------------------
// Timer
// ---------------------------------------------------------------------------

export const TIMER_KEY = ['timer'] as const;

export function useTimer() {
  return useQuery({
    queryKey: TIMER_KEY,
    queryFn: () => api.get<{ running: TimeEntry | null }>('/time-entries/timer/'),
    // The widget ticks locally; this keeps tabs/devices in sync.
    refetchInterval: 60_000,
  });
}

export interface TimerStartPayload {
  client?: string;
  project?: string;
  task?: string;
  service_type?: string;
  description?: string;
  billable?: boolean;
}

export function useStartTimer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: TimerStartPayload) =>
      api.post<TimeEntry>('/time-entries/timer/start/', payload),
    onSuccess: (entry) => {
      queryClient.setQueryData(TIMER_KEY, { running: entry });
      invalidateTimeWorld(queryClient);
    },
  });
}

export function useStopTimer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<TimeEntry>('/time-entries/timer/stop/'),
    onSuccess: () => {
      queryClient.setQueryData(TIMER_KEY, { running: null });
      invalidateTimeWorld(queryClient);
    },
  });
}
