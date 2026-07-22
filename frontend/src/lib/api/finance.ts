import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api/client';

export interface FinanceKPIs {
  revenue_ytd: string;
  revenue_month: string;
  revenue_quarter: string;
  open_receivables: string;
  overdue_receivables: string;
  draft_total: string;
  unbilled_seconds: number;
  unbilled_value: string;
  invoiced_total: string;
  paid_total: string;
  vat_invoiced_ytd: string;
}

export interface BreakdownRow {
  label: string;
  value: string;
}

export interface FinanceDashboard {
  kpis: FinanceKPIs;
  breakdown: { by_client: BreakdownRow[]; by_service: BreakdownRow[] };
  year: number;
}

export interface TraceStep {
  label: string;
  value: string;
  detail: string;
}

export interface SourceNote {
  field: string;
  source: string;
  note: string;
}

export interface ReserveForecast {
  available: boolean;
  message?: string;
  tax_year?: number;
  rule_version?: string;
  legal_form?: TaxProfile['legal_form'];
  projected_annual_profit?: string;
  profit_ytd?: string;
  revenue_ytd?: string;
  expenses_ytd?: string;
  income_tax?: string;
  corporate_tax?: string;
  soli?: string;
  church_tax?: string;
  trade_tax?: string;
  trade_tax_credit?: string;
  vat_reserve?: string;
  health_insurance?: string;
  safety_buffer?: string;
  recommended_reserve?: string;
  existing_reserve?: string;
  reserve_opening?: string;
  reserve_transfers_total?: string;
  last_transfer_date?: string | null;
  prepayments_made?: string;
  reserve_gap?: string;
  trace?: TraceStep[];
  sources?: SourceNote[];
  limitations?: string[];
  disclaimer: string;
}

export interface TaxProfile {
  id: string;
  tax_year: number;
  legal_form: 'sole' | 'freelancer' | 'ug' | 'gmbh';
  small_business: boolean;
  other_taxable_income: string;
  joint_assessment: boolean;
  trade_tax_multiplier: number;
  church_tax: boolean;
  federal_state: string;
  health_insurance_status: 'statutory_voluntary' | 'private' | 'family';
  estimated_monthly_health_insurance: string;
  safety_margin_percent: string;
  prepayments_made: string;
  existing_reserve: string;
}

export const LEGAL_FORM_LABELS: Record<TaxProfile['legal_form'], string> = {
  sole: 'Einzelunternehmen',
  freelancer: 'Freiberufler',
  ug: 'UG (haftungsbeschränkt)',
  gmbh: 'GmbH',
};

export function useFinanceDashboard() {
  return useQuery({
    queryKey: ['finance-dashboard'],
    queryFn: () => api.get<FinanceDashboard>('/finance/dashboard'),
  });
}

export function useReserve(year?: number) {
  return useQuery({
    queryKey: ['reserve', year ?? 'current'],
    queryFn: () => api.get<ReserveForecast>('/finance/reserve', { query: { year } }),
  });
}

/** Scenario: recompute the reserve for an overridden annual profit. */
export function useReserveScenario() {
  return useMutation({
    mutationFn: (input: { year?: number; annual_profit: number }) =>
      api.post<ReserveForecast>('/finance/reserve', input),
  });
}

export interface ReportMonth {
  month: string;
  invoiced_net: string;
  paid_net: string;
  seconds: number;
  billable_seconds: number;
}

export interface ReportClient {
  id: string;
  name: string;
  invoiced_net: string;
  open_gross: string;
  seconds: number;
  effective_rate: string | null;
  share: number;
}

export interface ReportService {
  name: string;
  value: string;
  seconds: number;
}

export interface ReportProject {
  id: string;
  name: string;
  client_name: string;
  seconds: number;
  budget_hours: string | null;
  budget_used_share: number | null;
  value: string;
  unbilled_value: string;
  invoiced_net: string;
}

export interface BusinessReport {
  year: number;
  generated_at: string;
  months: ReportMonth[];
  kpis: {
    revenue_ytd: string;
    revenue_month: string;
    revenue_quarter: string;
    avg_monthly_revenue: string;
    effective_hourly_rate: string | null;
    billable_share_90d: number | null;
    avg_days_to_pay: number | null;
    open_receivables: string;
    overdue_receivables: string;
    unbilled_value: string;
    unbilled_seconds: number;
    draft_total: string;
    active_clients_90d: number;
    total_clients: number;
    active_projects: number;
  };
  clients: ReportClient[];
  services: ReportService[];
  projects: ReportProject[];
  concentration: { client_name: string; share: number } | null;
}

export function useBusinessReport() {
  return useQuery({
    queryKey: ['business-report'],
    queryFn: () => api.get<BusinessReport>('/finance/report'),
  });
}

export interface ReserveTransfer {
  id: string;
  transfer_date: string;
  amount: string;
  note: string;
  source: 'manual' | 'lexware';
  source_display: string;
  created_at: string;
}

export function useReserveTransfers() {
  return useQuery({
    queryKey: ['reserve-transfers'],
    queryFn: () =>
      api.get<{ count: number; results: ReserveTransfer[] }>('/reserve-transfers/', {
        query: { page_size: 50 },
      }),
  });
}

export function useCreateReserveTransfer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { transfer_date: string; amount: string; note?: string }) =>
      api.post<ReserveTransfer>('/reserve-transfers/', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reserve-transfers'] });
      queryClient.invalidateQueries({ queryKey: ['reserve'] });
    },
  });
}

export function useDeleteReserveTransfer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/reserve-transfers/${id}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reserve-transfers'] });
      queryClient.invalidateQueries({ queryKey: ['reserve'] });
    },
  });
}

export function useTaxProfile() {
  return useQuery({
    queryKey: ['tax-profile', 'current'],
    queryFn: () => api.get<TaxProfile>('/tax-profiles/current/'),
  });
}

export function useUpdateTaxProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: Partial<TaxProfile> & { id: string }) =>
      api.patch<TaxProfile>(`/tax-profiles/${id}/`, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tax-profile'] });
      queryClient.invalidateQueries({ queryKey: ['reserve'] });
    },
  });
}
