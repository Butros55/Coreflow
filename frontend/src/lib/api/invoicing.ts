import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type Paginated } from '@/lib/api/client';

export type InvoiceStatus =
  'draft_local' | 'send_pending' | 'draft_remote' | 'open' | 'paid' | 'overdue' | 'voided';

export type TaxType = 'net' | 'gross' | 'vatfree';

export type InvoiceGrouping =
  'per_entry' | 'per_day' | 'per_service' | 'per_phase' | 'per_task' | 'lump_sum';

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  draft_local: 'Lokaler Entwurf',
  send_pending: 'Übertragung läuft',
  draft_remote: 'Lexware-Entwurf',
  open: 'Offen',
  paid: 'Bezahlt',
  overdue: 'Überfällig',
  voided: 'Storniert',
};

export const GROUPING_LABELS: Record<InvoiceGrouping, string> = {
  per_entry: 'Einzelposition',
  per_day: 'Pro Tag',
  per_service: 'Pro Leistungsart',
  per_phase: 'Pro Projektphase',
  per_task: 'Pro Aufgabe',
  lump_sum: 'Gesamtsumme',
};

export const TAX_TYPE_LABELS: Record<TaxType, string> = {
  net: 'Netto (zzgl. USt)',
  gross: 'Brutto (inkl. USt)',
  vatfree: 'Steuerfrei (§19 UStG)',
};

/** A time entry billed on an invoice line. `source === 'lexware_import'`
 * marks assignments the Lexware import matched automatically. */
export interface InvoiceLineTimeEntry {
  time_entry_id: string;
  started_at: string;
  description: string;
  duration_seconds: number;
  source: 'compose' | 'lexware_import';
}

export interface InvoiceLine {
  id: string;
  title: string;
  description: string;
  quantity: string;
  unit: string;
  unit_price: string;
  tax_rate: string;
  total_price: string;
  order: number;
  time_entries: InvoiceLineTimeEntry[];
}

export interface InvoiceListItem {
  id: string;
  client: string;
  client_name: string;
  project: string | null;
  status: InvoiceStatus;
  status_display: string;
  invoice_number: string;
  invoice_date: string | null;
  due_date: string | null;
  net_amount: string;
  tax_amount: string;
  gross_amount: string;
  open_amount: string;
  currency: string;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
}

export interface Invoice extends InvoiceListItem {
  title: string;
  introduction: string;
  remark: string;
  payment_term_days: number;
  tax_type: TaxType;
  tax_rate: string;
  grouping: InvoiceGrouping;
  paid_at: string | null;
  lexware_version: number | null;
  last_synced_at: string | null;
  lines: InvoiceLine[];
  is_editable: boolean;
  entry_count: number;
  updated_at: string;
}

export interface OpenEntry {
  id: string;
  started_at: string;
  description: string;
  project_name: string | null;
  service_type_name: string | null;
  duration_seconds: number;
  amount: string;
}

export interface OpenEntriesClient {
  client_id: string;
  client_name: string;
  currency: string;
  entries: OpenEntry[];
  total_seconds: number;
  total_amount: string;
}

// ---------------------------------------------------------------------------

export function useInvoices(
  params: { client?: string; project?: string; status?: InvoiceStatus } = {},
) {
  return useQuery({
    queryKey: ['invoices', params],
    queryFn: () =>
      api.get<Paginated<InvoiceListItem>>('/invoices/', {
        query: { ...params, page_size: 100 },
      }),
  });
}

export function useInvoice(id: string | null) {
  return useQuery({
    queryKey: ['invoice', id],
    queryFn: () => api.get<Invoice>(`/invoices/${id}/`),
    enabled: Boolean(id),
  });
}

export function useOpenEntries(clientId?: string) {
  return useQuery({
    queryKey: ['open-entries', clientId ?? 'all'],
    queryFn: () =>
      api.get<{ clients: OpenEntriesClient[] }>('/open-entries/', {
        query: { client: clientId },
      }),
  });
}

export interface ComposePayload {
  client: string;
  entry_ids: string[];
  grouping: InvoiceGrouping;
  project?: string | null;
  tax_type?: TaxType | null;
  payment_term_days?: number;
}

export interface PreviewLine {
  title: string;
  hours: string;
  amount: string;
  entry_count: number;
}

export function usePreviewInvoice() {
  return useMutation({
    mutationFn: (payload: ComposePayload) =>
      api.post<{ lines: PreviewLine[]; total: string; entry_count: number }>(
        '/invoices/preview/',
        payload,
      ),
  });
}

function invalidateInvoiceWorld(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ['invoices'] });
  queryClient.invalidateQueries({ queryKey: ['open-entries'] });
  queryClient.invalidateQueries({ queryKey: ['time-entries'] });
  queryClient.invalidateQueries({ queryKey: ['clients'] });
}

export function useComposeInvoice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ComposePayload) => api.post<Invoice>('/invoices/', payload),
    onSuccess: () => invalidateInvoiceWorld(queryClient),
  });
}

export interface InvoiceUpdatePayload {
  title?: string;
  introduction?: string;
  remark?: string;
  invoice_date?: string | null;
  payment_term_days?: number;
  tax_type?: TaxType;
  lines?: Array<{
    id?: string;
    title: string;
    description?: string;
    quantity: string;
    unit?: string;
    unit_price: string;
    tax_rate?: string;
  }>;
}

export function useUpdateInvoice(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: InvoiceUpdatePayload) => api.patch<Invoice>(`/invoices/${id}/`, patch),
    onSuccess: (invoice) => {
      queryClient.setQueryData(['invoice', id], invoice);
      invalidateInvoiceWorld(queryClient);
    },
  });
}

export function useSendInvoice(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Invoice>(`/invoices/${id}/send/`),
    onSuccess: (invoice) => {
      queryClient.setQueryData(['invoice', id], invoice);
      invalidateInvoiceWorld(queryClient);
    },
  });
}

export function useCancelInvoice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/invoices/${id}/`),
    onSuccess: () => invalidateInvoiceWorld(queryClient),
  });
}
