'use client';

import { AlertTriangle } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Input, Label } from '@/components/ui/input';
import { useEraseClient, type Client, type EraseClientResult } from '@/lib/api/crm';

export function DeleteClientDialog({
  client,
  open,
  onOpenChange,
  onDeleted,
}: {
  client: Client;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted?: (result: EraseClientResult) => void;
}) {
  const erase = useEraseClient();
  const [confirmName, setConfirmName] = React.useState('');

  const changeOpen = (nextOpen: boolean) => {
    onOpenChange(nextOpen);
    if (!nextOpen && !erase.isPending) setConfirmName('');
  };

  const confirm = () => {
    erase.mutate(
      { id: client.id, confirm: confirmName },
      {
        onSuccess: (result) => {
          changeOpen(false);
          toast.success(
            result.mode === 'deleted'
              ? 'Kunde vollständig gelöscht.'
              : 'Kunde anonymisiert. Aufbewahrungspflichtige Geschäftsdaten bleiben erhalten.',
          );
          onDeleted?.(result);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent
        title="Kunden löschen / anonymisieren"
        description="Die Aktion wird entsprechend der gesetzlichen Aufbewahrungspflichten ausgeführt."
      >
        <div className="space-y-4">
          <div className="flex gap-3 rounded-[var(--radius-md)] border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/8 p-3">
            <AlertTriangle
              className="mt-0.5 size-4 shrink-0 text-[var(--color-danger)]"
              aria-hidden
            />
            <p className="text-[length:var(--text-sm)] leading-relaxed text-[var(--color-ink-muted)]">
              Kontakte, Notizen und Aktivitäten werden unwiderruflich gelöscht. Gibt es Rechnungen,
              Zeiten oder Projekte, wird der Kunde aus rechtlichen Gründen anonymisiert; andernfalls
              wird er vollständig gelöscht.
            </p>
          </div>
          <div>
            <Label htmlFor={`delete-client-${client.id}`} required>
              Zur Bestätigung „{client.name}“ eingeben
            </Label>
            <Input
              id={`delete-client-${client.id}`}
              value={confirmName}
              onChange={(event) => setConfirmName(event.target.value)}
              autoComplete="off"
              autoFocus
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => changeOpen(false)}>
              Abbrechen
            </Button>
            <Button
              type="button"
              variant="danger"
              loading={erase.isPending}
              disabled={confirmName !== client.name}
              onClick={confirm}
            >
              Unwiderruflich löschen
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
