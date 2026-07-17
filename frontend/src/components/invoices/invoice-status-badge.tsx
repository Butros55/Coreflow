import { StatusTint, type StatusTone } from '@/components/ui/status-pill';
import { INVOICE_STATUS_LABELS, type InvoiceStatus } from '@/lib/api/invoicing';

const TONES: Record<InvoiceStatus, StatusTone> = {
  draft_local: 'hold',
  send_pending: 'progress',
  draft_remote: 'todo',
  open: 'review',
  paid: 'done',
  overdue: 'stuck',
  voided: 'neutral',
};

export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  return <StatusTint tone={TONES[status]}>{INVOICE_STATUS_LABELS[status]}</StatusTint>;
}
