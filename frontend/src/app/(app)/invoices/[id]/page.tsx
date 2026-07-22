'use client';

import { FileText, ArrowLeft, Clock3, ExternalLink, Info, Send, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/app-shell';
import { api } from '@/lib/api/client';
import { AssignProjectToInvoiceMenu } from '@/components/invoices/assign-invoice-menu';
import { DetailErrorState } from '@/components/ui/detail-error';
import { InvoiceStatusBadge } from '@/components/invoices/invoice-status-badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Label } from '@/components/ui/input';
import { Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import {
  TAX_TYPE_LABELS,
  useCancelInvoice,
  useInvoice,
  useSendInvoice,
  useUpdateInvoice,
  type Invoice,
  type InvoiceLine,
  type InvoiceLineTimeEntry,
  type TaxType,
} from '@/lib/api/invoicing';
import { usePermissions } from '@/lib/session';
import { cn, formatHours, formatMoney } from '@/lib/utils';

export default function InvoiceDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { data: invoice, isLoading, error } = useInvoice(params.id);
  const permissions = usePermissions();

  if (isLoading) {
    return (
      <div className="p-5 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</div>
    );
  }
  if (error || !invoice) {
    return (
      <DetailErrorState
        error={error}
        entityLabel="Rechnung"
        backHref="/invoices"
        backLabel="Alle Rechnungen"
      />
    );
  }

  const label = invoice.invoice_number || `Entwurf ${invoice.id.slice(0, 8)}`;
  const canEdit = permissions.can_write && invoice.is_editable;

  return (
    <>
      <PageHeader
        title={label}
        description={`${invoice.client_name} · ${invoice.entry_count} Zeiteinträge`}
        actions={
          <div className="flex items-center gap-2">
            <InvoiceStatusBadge status={invoice.status} />
            {invoice.lexware_url ? (
              <Button variant="secondary" size="sm" asChild>
                <a href={invoice.lexware_url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink aria-hidden /> In Lexware öffnen
                </a>
              </Button>
            ) : null}
            <PdfButton invoiceId={invoice.id} status={invoice.status} />
            <Button variant="ghost" size="sm" asChild>
              <Link href="/invoices">
                <ArrowLeft aria-hidden /> Alle Rechnungen
              </Link>
            </Button>
          </div>
        }
      >
        <div className="pb-4" />
      </PageHeader>

      <div className="grid gap-4 p-5 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <LinesPanel invoice={invoice} canEdit={canEdit} />
        </div>
        <div className="space-y-4">
          <TotalsPanel invoice={invoice} canEdit={canEdit} canAssign={permissions.can_write} />
          <ActionsPanel
            invoice={invoice}
            canWrite={permissions.can_write}
            onCancelled={() => router.push('/invoices')}
          />
        </div>
      </div>
    </>
  );
}

function LinesPanel({ invoice, canEdit }: { invoice: Invoice; canEdit: boolean }) {
  // Remount the editable buffer whenever the server data changes — a `key` reset
  // is the idiomatic "sync prop to state" without a state-setting effect.
  return (
    <LinesPanelEditor
      key={invoice.updated_at}
      invoiceId={invoice.id}
      taxType={invoice.tax_type}
      serverLines={invoice.lines}
      canEdit={canEdit}
    />
  );
}

function LinesPanelEditor({
  invoiceId,
  taxType,
  serverLines,
  canEdit,
}: {
  invoiceId: string;
  taxType: Invoice['tax_type'];
  serverLines: InvoiceLine[];
  canEdit: boolean;
}) {
  const update = useUpdateInvoice(invoiceId);
  const [lines, setLines] = React.useState<InvoiceLine[]>(serverLines);
  const [dirty, setDirty] = React.useState(false);

  const editLine = (id: string, field: keyof InvoiceLine, value: string) => {
    setLines((previous) =>
      previous.map((line) => (line.id === id ? { ...line, [field]: value } : line)),
    );
    setDirty(true);
  };

  const save = () => {
    update.mutate(
      {
        lines: lines.map((line) => ({
          id: line.id,
          title: line.title,
          description: line.description,
          quantity: line.quantity,
          unit: line.unit,
          unit_price: line.unit_price,
          tax_rate: line.tax_rate,
        })),
      },
      {
        onSuccess: () => {
          toast.success('Rechnung gespeichert.');
          setDirty(false);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  const inputClass =
    'rounded-[var(--radius-sm)] border border-transparent bg-transparent px-1.5 py-0.5 transition-[border-color,background-color,box-shadow] hover:border-[var(--color-line)] focus:border-[var(--color-brand)] focus:bg-[var(--color-panel)] focus:shadow-[0_0_0_3px_var(--color-brand-ring)] focus:outline-none';

  return (
    <Panel>
      <PanelHeader>
        <div className="flex items-baseline gap-2">
          <PanelTitle>Positionen</PanelTitle>
          <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            {lines.length}
          </span>
        </div>
        {canEdit && dirty ? (
          <Button variant="primary" size="sm" onClick={save} loading={update.isPending}>
            Speichern
          </Button>
        ) : null}
      </PanelHeader>
      <PanelBody className="p-2">
        <ul className="divide-y divide-[var(--color-line-subtle)]">
          {lines.map((line, index) => (
            <li key={line.id} className="flex gap-3.5 px-2.5 py-3.5 first:pt-2.5 last:pb-2.5">
              {/* Position number chip — gives the list rhythm without a table grid. */}
              <span
                className="tabular mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--color-brand-subtle)] text-[length:var(--text-2xs)] font-semibold text-[var(--color-brand)]"
                aria-hidden
              >
                {String(index + 1).padStart(2, '0')}
              </span>

              <div className="min-w-0 flex-1">
                {canEdit ? (
                  <input
                    value={line.title}
                    onChange={(event) => editLine(line.id, 'title', event.target.value)}
                    className={cn('w-full text-[length:var(--text-base)] font-medium', inputClass)}
                    aria-label="Positionsbezeichnung"
                  />
                ) : (
                  <div className="text-[length:var(--text-base)] font-medium">{line.title}</div>
                )}
                {line.description ? (
                  <div className="mt-0.5 text-[length:var(--text-xs)] leading-relaxed text-[var(--color-ink-muted)]">
                    {line.description}
                  </div>
                ) : null}
                {line.time_entries?.length ? <LineEntryChips entries={line.time_entries} /> : null}
              </div>

              <div className="flex shrink-0 flex-col items-end gap-0.5">
                <span className="tabular text-[length:var(--text-lg)] font-semibold">
                  {formatMoney(line.total_price)}
                </span>
                <span className="tabular flex items-center gap-1 text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
                  {canEdit ? (
                    <input
                      value={line.quantity}
                      onChange={(event) => editLine(line.id, 'quantity', event.target.value)}
                      className={cn('tabular w-14 text-right', inputClass)}
                      inputMode="decimal"
                      aria-label="Menge"
                    />
                  ) : (
                    <span>{Number(line.quantity).toLocaleString('de-DE')}</span>
                  )}
                  <span className="text-[var(--color-ink-subtle)]">{line.unit} ×</span>
                  {canEdit ? (
                    <input
                      value={line.unit_price}
                      onChange={(event) => editLine(line.id, 'unit_price', event.target.value)}
                      className={cn('tabular w-16 text-right', inputClass)}
                      inputMode="decimal"
                      aria-label="Einzelpreis"
                    />
                  ) : (
                    <span>{formatMoney(line.unit_price)}</span>
                  )}
                </span>
                <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                  {taxType === 'vatfree' ? 'steuerfrei' : `zzgl. ${Number(line.tax_rate)} % USt`}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </PanelBody>
    </Panel>
  );
}

/**
 * The billed time entries of a line, as scannable chips: date + hours each,
 * so the provenance of a position is visible without hovering.
 */
function LineEntryChips({ entries }: { entries: InvoiceLineTimeEntry[] }) {
  const fromLexware = entries.some((entry) => entry.source === 'lexware_import');
  const totalSeconds = entries.reduce((sum, entry) => sum + entry.duration_seconds, 0);
  const MAX_CHIPS = 4;
  const shown = entries.slice(0, MAX_CHIPS);
  const hidden = entries.length - shown.length;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      {shown.map((entry) => (
        <span
          key={entry.time_entry_id}
          title={entry.description || undefined}
          className="inline-flex items-center gap-1 rounded-full bg-[var(--color-panel-sunken)] px-2 py-0.5 text-[length:var(--text-2xs)] text-[var(--color-ink-muted)]"
        >
          <Clock3 className="size-3 text-[var(--color-ink-subtle)]" aria-hidden />
          {new Date(entry.started_at).toLocaleDateString('de-DE', {
            day: 'numeric',
            month: 'numeric',
          })}{' '}
          · {formatHours(entry.duration_seconds / 3600)}
        </span>
      ))}
      {hidden > 0 ? (
        <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
          +{hidden} weitere
        </span>
      ) : null}
      {entries.length > 1 ? (
        <span className="text-[length:var(--text-2xs)] font-medium text-[var(--color-ink-muted)]">
          Σ {formatHours(totalSeconds / 3600)}
        </span>
      ) : null}
      {fromLexware ? (
        <span className="inline-flex items-center rounded-full bg-[var(--color-info-soft)] px-2 py-0.5 text-[length:var(--text-2xs)] font-medium text-[var(--color-info)]">
          aus Lexware
        </span>
      ) : null}
    </div>
  );
}

function TotalsPanel({
  invoice,
  canEdit,
  canAssign,
}: {
  invoice: Invoice;
  canEdit: boolean;
  canAssign: boolean;
}) {
  const update = useUpdateInvoice(invoice.id);

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Summen</PanelTitle>
      </PanelHeader>
      <PanelBody className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
            Projekt
          </span>
          <div className="flex min-w-0 items-center gap-2">
            {invoice.project ? (
              <Link
                href={`/projects/${invoice.project}`}
                className="truncate text-[length:var(--text-sm)] font-medium text-[var(--color-brand)] hover:underline"
              >
                {invoice.project_name}
              </Link>
            ) : (
              <span className="text-[length:var(--text-sm)] text-[var(--color-ink-subtle)]">
                Nicht zugeordnet
              </span>
            )}
            {canAssign ? (
              <AssignProjectToInvoiceMenu
                invoiceId={invoice.id}
                clientId={invoice.client}
                currentProjectId={invoice.project}
              />
            ) : null}
          </div>
        </div>
        {canEdit ? (
          <div>
            <Label htmlFor="invoice-tax-type">Steuerart</Label>
            <Select
              id="invoice-tax-type"
              value={invoice.tax_type}
              onChange={(event) =>
                update.mutate(
                  { tax_type: event.target.value as TaxType },
                  { onError: (error) => toast.error(error.message) },
                )
              }
            >
              {Object.entries(TAX_TYPE_LABELS).map(([value, lbl]) => (
                <option key={value} value={value}>
                  {lbl}
                </option>
              ))}
            </Select>
          </div>
        ) : (
          <Row label="Steuerart" value={TAX_TYPE_LABELS[invoice.tax_type]} />
        )}
        <div className="space-y-1.5 border-t border-[var(--color-line)] pt-3">
          <Row label="Netto" value={formatMoney(invoice.net_amount, invoice.currency)} />
          <Row
            label={`USt (${Number(invoice.tax_rate)}%)`}
            value={formatMoney(invoice.tax_amount, invoice.currency)}
          />
          <div className="flex items-baseline justify-between border-t border-[var(--color-line)] pt-1.5">
            <span className="font-medium">Brutto</span>
            <span className="tabular text-[length:var(--text-xl)] font-semibold">
              {formatMoney(invoice.gross_amount, invoice.currency)}
            </span>
          </div>
        </div>
        {invoice.period_start && invoice.period_end ? (
          <div className="border-t border-[var(--color-line)] pt-3 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            Leistungszeitraum {new Date(invoice.period_start).toLocaleDateString('de-DE')} –{' '}
            {new Date(invoice.period_end).toLocaleDateString('de-DE')}
          </div>
        ) : null}
      </PanelBody>
    </Panel>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between text-[length:var(--text-sm)]">
      <span className="text-[var(--color-ink-muted)]">{label}</span>
      <span className="tabular">{value}</span>
    </div>
  );
}

function ActionsPanel({
  invoice,
  canWrite,
  onCancelled,
}: {
  invoice: Invoice;
  canWrite: boolean;
  onCancelled: () => void;
}) {
  const send = useSendInvoice(invoice.id);
  const cancel = useCancelInvoice();
  const [confirmCancel, setConfirmCancel] = React.useState(false);

  const isLocalDraft = invoice.status === 'draft_local';
  const isRemoteDraft = invoice.status === 'draft_remote';

  if (!canWrite) return null;

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Aktionen</PanelTitle>
      </PanelHeader>
      <PanelBody className="space-y-3">
        {isLocalDraft ? (
          <>
            <Button
              variant="primary"
              className="w-full"
              onClick={() =>
                send.mutate(undefined, {
                  onSuccess: () => toast.success('An Lexware übertragen.'),
                  onError: (error) => toast.error(error.message),
                })
              }
              loading={send.isPending}
            >
              <Send aria-hidden /> An Lexware übertragen
            </Button>
            <div className="flex gap-2 rounded-[var(--radius-sm)] border border-[var(--color-line)] bg-[var(--color-panel-sunken)] p-2.5 text-[length:var(--text-2xs)] text-[var(--color-ink-muted)]">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <p>
                Erstellt einen <strong>Entwurf</strong> in Lexware. Die rechtsgültige Finalisierung
                erfolgt dort — die Lexware-API kann einen Entwurf nachträglich nicht finalisieren.
              </p>
            </div>
          </>
        ) : null}

        {isRemoteDraft ? (
          <div className="flex gap-2 rounded-[var(--radius-sm)] border border-[var(--color-info)] bg-[var(--color-info-soft)] p-2.5 text-[length:var(--text-2xs)] text-[var(--color-info)]">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <p>
              Als Entwurf in Lexware vorhanden. Zum Finalisieren in Lexware öffnen; Status,
              Rechnungsnummer und PDF werden anschließend synchronisiert.
            </p>
          </div>
        ) : null}

        {isLocalDraft || isRemoteDraft ? (
          <Button
            variant="ghost"
            className="w-full text-[var(--color-danger)]"
            onClick={() => setConfirmCancel(true)}
          >
            <Trash2 aria-hidden /> Entwurf verwerfen
          </Button>
        ) : null}

        {invoice.status === 'open' || invoice.status === 'paid' ? (
          <p className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            {invoice.status === 'paid'
              ? `Bezahlt am ${invoice.paid_at ? new Date(invoice.paid_at).toLocaleDateString('de-DE') : ''}.`
              : 'Finalisiert. Zahlungsstatus wird aus Lexware synchronisiert.'}
          </p>
        ) : null}
      </PanelBody>

      <Dialog open={confirmCancel} onOpenChange={setConfirmCancel}>
        <DialogContent
          title="Entwurf verwerfen?"
          description="Die zugeordneten Zeiteinträge werden wieder als „offen“ freigegeben."
        >
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmCancel(false)}>
              Abbrechen
            </Button>
            <Button
              variant="danger"
              loading={cancel.isPending}
              onClick={() =>
                cancel.mutate(invoice.id, {
                  onSuccess: () => {
                    toast.success('Entwurf verworfen.');
                    onCancelled();
                  },
                  onError: (error) => toast.error(error.message),
                })
              }
            >
              Verwerfen
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}

function PdfButton({ invoiceId, status }: { invoiceId: string; status: Invoice['status'] }) {
  const [busy, setBusy] = React.useState(false);
  // Only finalised vouchers have a rendered document — Lexware refuses to
  // render drafts by design, so the button never shows for them.
  if (!['open', 'overdue', 'paid', 'voided'].includes(status)) return null;

  const open = async () => {
    setBusy(true);
    try {
      // fetch → blob → objectURL: a plain window.open cannot send the
      // workspace header, so the request goes through the API client.
      const blob = await api.get<Blob>(`/invoices/${invoiceId}/pdf/`);
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'PDF konnte nicht geladen werden.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button variant="secondary" size="sm" loading={busy} onClick={open}>
      <FileText aria-hidden /> PDF anzeigen
    </Button>
  );
}
