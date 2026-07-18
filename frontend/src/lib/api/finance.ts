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
  projected_annual_profit?: string;
  profit_ytd?: string;
  revenue_ytd?: string;
  expenses_ytd?: string;
  income_tax?: string;
  soli?: string;
  church_tax?: string;
  trade_tax?: string;
  trade_tax_credit?: string;
  vat_reserve?: string;
  health_insurance?: string;
  safety_buffer?: string;
  recommended_reserve?: string;
  existing_reserve?: string;
  prepayments_made?: string;
  reserve_gap?: string;
  trace?: TraceStep[];
  sources?: SourceNote[];
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
