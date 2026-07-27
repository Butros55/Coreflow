'use client';

import { ArrowRight, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { DataTable, Td } from '@/components/ui/group-bar';
import { Label } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import {
  GROUPING_LABELS,
  useComposeInvoice,
  useOpenEntries,
  usePreviewInvoice,
  type InvoiceGrouping,
  type OpenEntriesClient,
} from '@/lib/api/invoicing';
import { formatHours, formatMoney } from '@/lib/utils';

/**
 * The invoice-from-open-hours flow (reference: the invoicing workflow in
 * lexware.md §6): pick a client's open entries → choose grouping → preview →
 * create a local draft. Entirely local; Lexware is only involved when the draft
 * is later "sent" from the detail page.
 */
export function CreateInvoiceDialog({
  open,
  onOpenChange,
  initialClientId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialClientId?: string;
}) {
  const router = useRouter();
  const { data, isLoading } = useOpenEntries();
  const compose = useComposeInvoice();
  const preview = usePreviewInvoice();

  const clients = React.useMemo(() => data?.clients ?? [], [data]);
  const [grouping, setGrouping] = React.useState<InvoiceGrouping>('per_service');
  // null = "not chosen yet"; the effective client defaults to the first one.
  const [chosenClientId, setChosenClientId] = React.useState<string | null>(
    initialClientId ?? null,
  );
  // Entries the user has explicitly deselected, per client. Everything not in
  // here is selected — so a freshly loaded client starts fully selected without
  // a state-sync effect.
  const [deselected, setDeselected] = React.useState<Set<string>>(new Set());

  const clientId = chosenClientId ?? clients[0]?.client_id ?? '';
  const activeClient: OpenEntriesClient | undefined = React.useMemo(
    () => clients.find((c) => c.client_id === clientId),
    [clients, clientId],
  );

  const selectedIds = React.useMemo(
    () => (activeClient?.entries ?? []).filter((e) => !deselected.has(e.id)).map((e) => e.id),
    [activeClient, deselected],
  );
  const selectedSet = React.useMemo(() => new Set(selectedIds), [selectedIds]);

  const selectClient = (id: string) => {
    setChosenClientId(id);
    setDeselected(new Set()); // new client → all selected
  };

  const selectedEntries = activeClient?.entries.filter((e) => selectedSet.has(e.id)) ?? [];
  const selectedTotal = selectedEntries.reduce((sum, e) => sum + Number(e.amount), 0);

  const previewLines = preview.data?.lines ?? [];

  // Re-preview whenever the selection or grouping changes. Reading the mutation
  // fn from a ref-stable binding keeps the dependency list honest.
  const previewMutate = preview.mutate;
  React.useEffect(() => {
    if (!clientId || selectedIds.length === 0) return;
    previewMutate({ client: clientId, entry_ids: selectedIds, grouping });
  }, [clientId, grouping, selectedIds, previewMutate]);

  const toggle = (id: string) => {
    setDeselected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const allSelected = activeClient ? selectedSet.size === activeClient.entries.length : false;
  const toggleAll = () => {
    setDeselected(allSelected ? new Set(activeClient?.entries.map((e) => e.id)) : new Set());
  };

  const submit = () => {
    if (!clientId || selectedIds.length === 0) return;
    compose.mutate(
      { client: clientId, entry_ids: selectedIds, grouping },
      {
        onSuccess: (invoice) => {
          toast.success('Rechnungsentwurf erstellt.');
          onOpenChange(false);
          router.push(`/invoices/${invoice.id}`);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Rechnung aus offenen Zeiten"
        description="Zeiteinträge auswählen, gruppieren und als Entwurf erstellen."
        wide
      >
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Loader2
              className="size-5 animate-spin text-[var(--color-ink-subtle)]"
              aria-label="Lädt"
            />
          </div>
        ) : clients.length === 0 ? (
          <p className="py-6 text-center text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
            Keine offenen abrechenbaren Zeiten vorhanden.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="invoice-client">Kunde</Label>
                <Select
                  id="invoice-client"
                  value={clientId}
                  onChange={(event) => selectClient(event.target.value)}
                >
                  {clients.map((client) => (
                    <option key={client.client_id} value={client.client_id}>
                      {client.client_name} · {formatHours(client.total_seconds / 3600)} offen
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="invoice-grouping">Gruppierung</Label>
                <Select
                  id="invoice-grouping"
                  value={grouping}
                  onChange={(event) => setGrouping(event.target.value as InvoiceGrouping)}
                >
                  {/* per_phase stays valid for legacy invoices but is no longer
                      offered — planning works with sprints, not phases. */}
                  {Object.entries(GROUPING_LABELS)
                    .filter(([value]) => value !== 'per_phase')
                    .map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {/* Entry picker */}
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-[length:var(--text-xs)] font-medium text-[var(--color-ink-muted)]">
                    Zeiteinträge ({selectedSet.size}/{activeClient?.entries.length ?? 0})
                  </span>
                  <button
                    type="button"
                    className="text-[length:var(--text-2xs)] text-[var(--color-brand)] hover:underline"
                    onClick={toggleAll}
                  >
                    {allSelected ? 'Keine' : 'Alle'}
                  </button>
                </div>
                <div className="max-h-64 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--color-line)]">
                  <DataTable>
                    <tbody>
                      {activeClient?.entries.map((entry) => (
                        <tr
                          key={entry.id}
                          className="cursor-pointer hover:bg-[var(--color-panel-raised)] last:[&>td]:border-b-0"
                          onClick={() => toggle(entry.id)}
                        >
                          <Td className="w-8">
                            <input
                              type="checkbox"
                              checked={selectedSet.has(entry.id)}
                              onChange={() => toggle(entry.id)}
                              onClick={(event) => event.stopPropagation()}
                              className="size-3.5 accent-[var(--color-brand)]"
                              aria-label={entry.description || 'Zeiteintrag'}
                            />
                          </Td>
                          <Td>
                            <div className="text-[length:var(--text-xs)]">
                              {entry.description || entry.service_type_name || 'Leistung'}
                            </div>
                            <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                              {new Date(entry.started_at).toLocaleDateString('de-DE')}
                              {entry.service_type_name ? ` · ${entry.service_type_name}` : ''}
                            </div>
                          </Td>
                          <Td className="tabular text-right text-[length:var(--text-xs)]">
                            {formatHours(entry.duration_seconds / 3600)}
                          </Td>
                          <Td className="tabular text-right text-[length:var(--text-xs)]">
                            {formatMoney(entry.amount)}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </div>
              </div>

              {/* Live preview */}
              <div>
                <div className="mb-1.5 flex items-center gap-1.5 text-[length:var(--text-xs)] font-medium text-[var(--color-ink-muted)]">
                  Rechnungsvorschau
                  {preview.isPending ? (
                    <Loader2 className="size-3 animate-spin" aria-hidden />
                  ) : null}
                </div>
                <div className="rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-panel-sunken)] p-3">
                  {previewLines.length === 0 ? (
                    <p className="py-4 text-center text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
                      Keine Auswahl
                    </p>
                  ) : (
                    <ul className="space-y-2">
                      {previewLines.map((line, index) => (
                        <li key={index} className="flex items-baseline justify-between gap-2">
                          <span className="min-w-0 flex-1 truncate text-[length:var(--text-sm)]">
                            {line.title}
                            <span className="ml-1.5 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                              {formatHours(Number(line.hours))}
                            </span>
                          </span>
                          <span className="tabular text-[length:var(--text-sm)] font-medium">
                            {formatMoney(line.amount)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="mt-3 flex items-baseline justify-between border-t border-[var(--color-line)] pt-2">
                    <span className="text-[length:var(--text-sm)] font-medium">Netto gesamt</span>
                    <span className="tabular text-[length:var(--text-lg)] font-semibold">
                      {formatMoney(selectedTotal.toFixed(2))}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between border-t border-[var(--color-line)] pt-3">
              <p className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                Erstellt einen lokalen Entwurf. Die Übertragung an Lexware erfolgt separat.
              </p>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => onOpenChange(false)}>
                  Abbrechen
                </Button>
                <Button
                  variant="primary"
                  onClick={submit}
                  loading={compose.isPending}
                  disabled={selectedIds.length === 0}
                >
                  Entwurf erstellen <ArrowRight aria-hidden />
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
