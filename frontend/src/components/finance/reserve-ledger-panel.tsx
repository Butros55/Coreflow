'use client';

import { PiggyBank, Plus, Trash2 } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { FieldError, Input, Label } from '@/components/ui/input';
import { EmptyState, Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import {
  useCreateReserveTransfer,
  useDeleteReserveTransfer,
  useReserveTransfers,
} from '@/lib/api/finance';
import { cn, formatMoney } from '@/lib/utils';

function todayInput(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * The reserve ledger: every transfer to (or from) the tax-reserve pot.
 *
 * A dated journal instead of one editable number — the Ist-Rücklage in the
 * forecast is opening balance + this ledger, so it stays current without a
 * bank connection (the Lexware Public API offers no account balances).
 */
export function ReserveLedgerPanel({ canManage }: { canManage: boolean }) {
  const { data, isLoading } = useReserveTransfers();
  const deleteTransfer = useDeleteReserveTransfer();
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const transfers = data?.results ?? [];

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          <span className="inline-flex items-center gap-1.5">
            <PiggyBank className="size-4" aria-hidden /> Rücklagenkonto
          </span>
        </PanelTitle>
        {canManage ? (
          <Button variant="secondary" size="xs" onClick={() => setDialogOpen(true)}>
            <Plus aria-hidden /> Übertrag
          </Button>
        ) : null}
      </PanelHeader>
      <PanelBody className="p-2">
        {isLoading ? (
          <p className="p-2 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : transfers.length === 0 ? (
          <EmptyState
            icon={<PiggyBank className="size-7" aria-hidden />}
            title="Noch keine Überträge"
            description="Erfasse hier jede Überweisung auf dein Rücklagenkonto — die Ist-Rücklage in der Prognose rechnet damit."
          />
        ) : (
          <ul>
            {transfers.map((transfer) => {
              const negative = Number(transfer.amount) < 0;
              return (
                <li
                  key={transfer.id}
                  className="group flex items-center gap-2.5 rounded-[var(--radius-md)] px-2.5 py-2 transition-colors hover:bg-[var(--color-panel-raised)]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[length:var(--text-sm)] font-medium">
                        {new Date(transfer.transfer_date).toLocaleDateString('de-DE')}
                      </span>
                      {transfer.source === 'lexware' ? (
                        <StatusTint tone="todo">Lexware</StatusTint>
                      ) : null}
                    </div>
                    {transfer.note ? (
                      <div className="truncate text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                        {transfer.note}
                      </div>
                    ) : null}
                  </div>
                  <span
                    className={cn(
                      'tabular shrink-0 text-[length:var(--text-sm)] font-semibold',
                      negative ? 'text-[var(--color-danger)]' : 'text-[var(--color-success)]',
                    )}
                  >
                    {negative ? '' : '+'}
                    {formatMoney(transfer.amount)}
                  </span>
                  {canManage ? (
                    <button
                      type="button"
                      aria-label="Übertrag löschen"
                      className="rounded-full p-1 text-[var(--color-ink-subtle)] opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[var(--color-danger-soft)] hover:text-[var(--color-danger)] focus-visible:opacity-100"
                      onClick={() =>
                        deleteTransfer.mutate(transfer.id, {
                          onSuccess: () => toast.success('Übertrag gelöscht.'),
                          onError: () => toast.error('Löschen fehlgeschlagen.'),
                        })
                      }
                    >
                      <Trash2 className="size-3.5" aria-hidden />
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </PanelBody>
      <TransferDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </Panel>
  );
}

function TransferDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateReserveTransfer();
  const [direction, setDirection] = React.useState<'in' | 'out'>('in');
  const [amount, setAmount] = React.useState('');
  const [date, setDate] = React.useState(todayInput);
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const reset = () => {
    setDirection('in');
    setAmount('');
    setDate(todayInput());
    setNote('');
    setError(null);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = Number(amount.replace(',', '.'));
    if (!Number.isFinite(value) || value <= 0) {
      setError('Bitte einen Betrag größer 0 angeben.');
      return;
    }
    const signed = direction === 'out' ? -value : value;
    create.mutate(
      { transfer_date: date, amount: signed.toFixed(2), note },
      {
        onSuccess: () => {
          toast.success(direction === 'out' ? 'Entnahme erfasst.' : 'Zuführung erfasst.');
          onOpenChange(false);
          reset();
        },
        onError: (mutationError) => setError(mutationError.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Übertrag erfassen"
        description="Eine Buchung auf dem Rücklagenkonto — z. B. die monatliche Überweisung auf das Tagesgeldkonto."
      >
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="inline-flex items-center gap-1 rounded-full bg-[var(--color-panel-sunken)] p-1">
            {(
              [
                { key: 'in', label: 'Zuführung' },
                { key: 'out', label: 'Entnahme' },
              ] as const
            ).map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setDirection(option.key)}
                className={cn(
                  'rounded-full px-3.5 py-1.5 text-[length:var(--text-sm)] transition-colors',
                  direction === option.key
                    ? 'bg-[var(--color-panel)] font-medium text-[var(--color-ink)] shadow-[var(--shadow-panel)]'
                    : 'text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="transfer-amount" required>
                Betrag (€)
              </Label>
              <Input
                id="transfer-amount"
                inputMode="decimal"
                placeholder="z. B. 500,00"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                autoFocus
              />
            </div>
            <div>
              <Label htmlFor="transfer-date" required>
                Datum
              </Label>
              <Input
                id="transfer-date"
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
              />
            </div>
          </div>

          <div>
            <Label htmlFor="transfer-note">Notiz</Label>
            <Input
              id="transfer-note"
              placeholder="z. B. Rücklage Juli"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={200}
            />
          </div>

          <FieldError>{error}</FieldError>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button type="submit" variant="primary" loading={create.isPending}>
              Erfassen
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
