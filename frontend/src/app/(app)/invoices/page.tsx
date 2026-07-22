'use client';

import { FileText, HandCoins, Plus, Receipt } from 'lucide-react';
import { useRouter } from 'next/navigation';
import * as React from 'react';

import { PageHeader } from '@/components/layout/app-shell';
import { AssignProjectToInvoiceMenu } from '@/components/invoices/assign-invoice-menu';
import { CreateInvoiceDialog } from '@/components/invoices/create-invoice-dialog';
import { InvoiceStatusBadge } from '@/components/invoices/invoice-status-badge';
import { Button } from '@/components/ui/button';
import { ClickableRow, DataTable, GroupSection, Td, Th } from '@/components/ui/group-bar';
import { EmptyState, StatTile } from '@/components/ui/panel';
import { useInvoices, type InvoiceListItem, type InvoiceStatus } from '@/lib/api/invoicing';
import { usePermissions } from '@/lib/session';
import { formatMoney } from '@/lib/utils';

const GROUPS: { statuses: InvoiceStatus[]; title: string; color: string }[] = [
  {
    statuses: ['draft_local', 'draft_remote', 'send_pending'],
    title: 'Entwürfe',
    color: 'var(--color-status-hold)',
  },
  { statuses: ['open', 'overdue'], title: 'Offen', color: 'var(--color-status-review)' },
  { statuses: ['paid'], title: 'Bezahlt', color: 'var(--color-status-done)' },
  { statuses: ['voided'], title: 'Storniert', color: 'var(--color-status-stuck)' },
];

export default function InvoicesPage() {
  const router = useRouter();
  const permissions = usePermissions();
  const [createOpen, setCreateOpen] = React.useState(false);
  const { data, isLoading } = useInvoices();
  const invoices = React.useMemo(() => data?.results ?? [], [data]);

  const openTotal = invoices
    .filter((inv) => inv.status === 'open' || inv.status === 'overdue')
    .reduce((sum, inv) => sum + Number(inv.open_amount), 0);
  const draftTotal = invoices
    .filter((inv) => ['draft_local', 'draft_remote', 'send_pending'].includes(inv.status))
    .reduce((sum, inv) => sum + Number(inv.gross_amount), 0);
  const thisYear = String(new Date().getFullYear());
  const paidThisYear = invoices
    .filter((inv) => inv.status === 'paid' && (inv.invoice_date ?? '').startsWith(thisYear))
    .reduce((sum, inv) => sum + Number(inv.gross_amount), 0);

  const groups = GROUPS.map((group) => ({
    ...group,
    invoices: invoices.filter((inv) => group.statuses.includes(inv.status)),
  })).filter((group) => group.invoices.length > 0);

  return (
    <>
      <PageHeader
        title="Rechnungen"
        description={`${data?.count ?? '…'} Rechnungen`}
        actions={
          permissions.can_write ? (
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden /> Rechnung erstellen
            </Button>
          ) : undefined
        }
      >
        <div className="pb-4" />
      </PageHeader>

      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile
            icon={<Receipt />}
            label="Offene Forderungen"
            value={formatMoney(openTotal.toFixed(2))}
            tone={openTotal > 0 ? 'warning' : 'default'}
            hint="Versendet, noch nicht bezahlt"
          />
          <StatTile
            icon={<FileText />}
            label="Entwürfe"
            value={formatMoney(draftTotal.toFixed(2))}
            hint="Noch nicht versendet"
          />
          <StatTile
            icon={<HandCoins />}
            label="Bezahlt (Jahr)"
            value={formatMoney(paidThisYear.toFixed(2))}
            tone={paidThisYear > 0 ? 'success' : 'default'}
            hint="Zahlungseingänge dieses Jahr"
          />
        </div>

        {isLoading ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : groups.length === 0 ? (
          <EmptyState
            icon={<Receipt className="size-8" aria-hidden />}
            title="Noch keine Rechnungen"
            description="Erstelle eine Rechnung aus offenen, abrechenbaren Zeiteinträgen."
            action={
              permissions.can_write ? (
                <Button variant="primary" onClick={() => setCreateOpen(true)}>
                  <Plus aria-hidden /> Rechnung erstellen
                </Button>
              ) : undefined
            }
          />
        ) : (
          groups.map((group) => (
            <GroupSection
              key={group.title}
              color={group.color}
              title={group.title}
              count={group.invoices.length}
            >
              <DataTable>
                <thead>
                  <tr>
                    <Th>Nummer / Entwurf</Th>
                    <Th>Kunde</Th>
                    <Th>Projekt</Th>
                    <Th>Status</Th>
                    <Th>Datum</Th>
                    <Th className="text-right">Netto</Th>
                    <Th className="text-right">Brutto</Th>
                    <Th className="text-right">Offen</Th>
                  </tr>
                </thead>
                <tbody>
                  {group.invoices.map((invoice) => (
                    <InvoiceRow
                      key={invoice.id}
                      invoice={invoice}
                      canAssign={permissions.can_write}
                      onOpen={() => router.push(`/invoices/${invoice.id}`)}
                    />
                  ))}
                </tbody>
              </DataTable>
            </GroupSection>
          ))
        )}
      </div>

      <CreateInvoiceDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}

function InvoiceRow({
  invoice,
  canAssign,
  onOpen,
}: {
  invoice: InvoiceListItem;
  canAssign: boolean;
  onOpen: () => void;
}) {
  return (
    <ClickableRow onClick={onOpen} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen()}>
      <Td className="font-medium">
        {invoice.invoice_number || `Entwurf ${invoice.id.slice(0, 8)}`}
      </Td>
      <Td className="text-[var(--color-ink-muted)]">{invoice.client_name}</Td>
      <Td>
        {/* The menu lives inside a clickable row — keep its clicks local. */}
        <span onClick={(event) => event.stopPropagation()}>
          {invoice.project ? (
            canAssign ? (
              <AssignProjectToInvoiceMenu
                invoiceId={invoice.id}
                clientId={invoice.client}
                currentProjectId={invoice.project}
                trigger={
                  <button
                    type="button"
                    className="max-w-40 truncate text-left text-[var(--color-brand)] hover:underline"
                    title="Projektzuordnung ändern"
                  >
                    {invoice.project_name}
                  </button>
                }
              />
            ) : (
              <span className="max-w-40 truncate">{invoice.project_name}</span>
            )
          ) : canAssign ? (
            <AssignProjectToInvoiceMenu
              invoiceId={invoice.id}
              clientId={invoice.client}
              currentProjectId={null}
              trigger={
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-full border border-dashed border-[var(--color-line-strong)] px-2 py-0.5 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)] transition-colors hover:border-[var(--color-brand)] hover:text-[var(--color-brand)]"
                >
                  <Plus className="size-3" aria-hidden /> Zuordnen
                </button>
              }
            />
          ) : (
            <span className="text-[var(--color-ink-subtle)]">—</span>
          )}
        </span>
      </Td>
      <Td>
        <InvoiceStatusBadge status={invoice.status} />
      </Td>
      <Td className="text-[var(--color-ink-muted)]">
        {invoice.invoice_date
          ? new Date(invoice.invoice_date).toLocaleDateString('de-DE')
          : new Date(invoice.created_at).toLocaleDateString('de-DE')}
      </Td>
      <Td className="tabular text-right">{formatMoney(invoice.net_amount, invoice.currency)}</Td>
      <Td className="tabular text-right font-medium">
        {formatMoney(invoice.gross_amount, invoice.currency)}
      </Td>
      <Td className="tabular text-right">
        {Number(invoice.open_amount) > 0 ? (
          <span className="text-[var(--color-warning)]">
            {formatMoney(invoice.open_amount, invoice.currency)}
          </span>
        ) : (
          '—'
        )}
      </Td>
    </ClickableRow>
  );
}
