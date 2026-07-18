'use client';

import { ArrowLeft, Info, Send, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/app-shell';
import { DetailErrorState } from '@/components/ui/detail-error';
import { InvoiceStatusBadge } from '@/components/invoices/invoice-status-badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { DataTable, Td, Th } from '@/components/ui/group-bar';
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
  type TaxType,
} from '@/lib/api/invoicing';
import { usePermissions } from '@/lib/session';
import { formatMoney } from '@/lib/utils';

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
          <TotalsPanel invoice={invoice} canEdit={canEdit} />
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

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Positionen</PanelTitle>
        {canEdit && dirty ? (
          <Button variant="primary" size="sm" onClick={save} loading={update.isPending}>
            Speichern
          </Button>
        ) : null}
      </PanelHeader>
      <DataTable>
        <thead>
          <tr>
            <Th className="w-[40%]">Bezeichnung</Th>
            <Th className="text-right">Menge</Th>
            <Th className="text-right">Einzelpreis</Th>
            <Th className="text-right">USt %</Th>
            <Th className="text-right">Gesamt</Th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.id} className="last:[&>td]:border-b-0">
              <Td>
                {canEdit ? (
                  <input
                    value={line.title}
                    onChange={(event) => editLine(line.id, 'title', event.target.value)}
                    className="w-full bg-transparent text-[length:var(--text-sm)] outline-none focus:rounded focus:ring-2 focus:ring-[var(--color-brand-ring)]"
                    aria-label="Positionsbezeichnung"
                  />
                ) : (
                  line.title
                )}
                {line.description ? (
                  <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    {line.description}
                  </div>
                ) : null}
              </Td>
              <Td className="text-right">
                {canEdit ? (
                  <input
                    value={line.quantity}
                    onChange={(event) => editLine(line.id, 'quantity', event.target.value)}
                    className="tabular w-16 bg-transparent text-right outline-none focus:rounded focus:ring-2 focus:ring-[var(--color-brand-ring)]"
                    inputMode="decimal"
                    aria-label="Menge"
                  />
                ) : (
                  <span className="tabular">{line.quantity}</span>
                )}{' '}
                <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                  {line.unit}
                </span>
              </Td>
              <Td className="text-right">
                {canEdit ? (
                  <input
                    value={line.unit_price}
                    onChange={(event) => editLine(line.id, 'unit_price', event.target.value)}
                    className="tabular w-20 bg-transparent text-right outline-none focus:rounded focus:ring-2 focus:ring-[var(--color-brand-ring)]"
                    inputMode="decimal"
                    aria-label="Einzelpreis"
                  />
                ) : (
                  <span className="tabular">{formatMoney(line.unit_price)}</span>
                )}
              </Td>
              <Td className="tabular text-right text-[var(--color-ink-muted)]">
                {taxType === 'vatfree' ? '—' : `${Number(line.tax_rate)}%`}
              </Td>
              <Td className="tabular text-right font-medium">{formatMoney(line.total_price)}</Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </Panel>
  );
}

function TotalsPanel({ invoice, canEdit }: { invoice: Invoice; canEdit: boolean }) {
  const update = useUpdateInvoice(invoice.id);

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Summen</PanelTitle>
      </PanelHeader>
      <PanelBody className="space-y-3">
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
