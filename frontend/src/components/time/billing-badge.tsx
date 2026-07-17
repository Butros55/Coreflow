import { StatusTint, type StatusTone } from '@/components/ui/status-pill';

const MAP: Record<string, { tone: StatusTone; label: string }> = {
  open: { tone: 'todo', label: 'Offen' },
  not_billable: { tone: 'hold', label: 'Nicht abrechenbar' },
  marked_for_invoice: { tone: 'progress', label: 'Vorgemerkt' },
  invoice_draft_created: { tone: 'progress', label: 'Entwurf' },
  billed: { tone: 'done', label: 'Abgerechnet' },
  cancelled: { tone: 'stuck', label: 'Storniert' },
};

/** Billing-status chip for time entries; unknown statuses render verbatim. */
export function BillingBadge({ status }: { status: string }) {
  const entry = MAP[status] ?? { tone: 'hold' as StatusTone, label: status };
  return <StatusTint tone={entry.tone}>{entry.label}</StatusTint>;
}
