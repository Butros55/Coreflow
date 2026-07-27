import Link from 'next/link';

import { StatusTint, type StatusTone } from '@/components/ui/status-pill';
import type { TimeEntry, TimeEntryInvoiceLink } from '@/lib/api/time';

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

/**
 * Which invoice an entry is billed on. Assignments the Lexware import matched
 * automatically carry an extra "Lexware" marker so they are distinguishable
 * from invoices composed locally.
 */
export function InvoiceLinkChip({ link }: { link: TimeEntryInvoiceLink }) {
  const fromLexware = link.source === 'lexware_import';
  return (
    <Link
      href={`/invoices/${link.invoice_id}`}
      title={
        fromLexware
          ? 'Beim Lexware-Import automatisch zugeordnet'
          : 'Über die Rechnungserstellung zugeordnet'
      }
      className="inline-flex items-center gap-1 rounded-[var(--radius-xs)] border border-[var(--color-line)] px-1.5 py-0.5 text-[length:var(--text-2xs)] text-[var(--color-ink-muted)] hover:border-[var(--color-brand)] hover:text-[var(--color-brand)]"
    >
      {link.invoice_number || 'Entwurf'}
      {fromLexware ? (
        <span className="font-medium text-[var(--color-brand)]">· Lexware</span>
      ) : null}
    </Link>
  );
}

const TAG_META: Record<string, { label: string; title: string }> = {
  lexware: {
    label: 'Lexware',
    title: 'In Lexware vorhanden (importiert oder dort abgerechnet)',
  },
  clockify: {
    label: 'Clockify',
    title: 'Mit Clockify synchronisiert',
  },
};

/**
 * Which external systems an entry exists in. A deduplicated entry (e.g. from
 * Lexware billed, in Clockify getrackt) shows BOTH chips on one row — that is
 * the point: one entry, two tags, never two entries.
 */
export function IntegrationTagChips({ tags }: { tags: TimeEntry['integration_tags'] }) {
  if (!tags || tags.length === 0) return null;
  return (
    <>
      {tags.map((tag) => {
        const meta = TAG_META[tag] ?? { label: tag, title: tag };
        return (
          <span
            key={tag}
            title={meta.title}
            className="inline-flex items-center rounded-[var(--radius-xs)] border border-[var(--color-line)] bg-[var(--color-panel-sunken)] px-1.5 py-0.5 text-[length:var(--text-2xs)] font-medium text-[var(--color-brand)]"
          >
            {meta.label}
          </span>
        );
      })}
    </>
  );
}
