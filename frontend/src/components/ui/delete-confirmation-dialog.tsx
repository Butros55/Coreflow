'use client';

import { AlertTriangle } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';

export interface DeleteConfirmationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  itemName: string;
  message?: React.ReactNode;
  confirmLabel?: string;
  isPending?: boolean;
  onConfirm: () => void;
}

/** A consistent safety gate for irreversible delete actions. */
export function DeleteConfirmationDialog({
  open,
  onOpenChange,
  title,
  itemName,
  message,
  confirmLabel = 'Unwiderruflich löschen',
  isPending = false,
  onConfirm,
}: DeleteConfirmationDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={title} description={`„${itemName}“ wird gelöscht.`}>
        <div className="space-y-4">
          <div className="flex gap-3 rounded-[var(--radius-md)] border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/8 p-3">
            <AlertTriangle
              className="mt-0.5 size-4 shrink-0 text-[var(--color-danger)]"
              aria-hidden
            />
            <p className="text-[length:var(--text-sm)] leading-relaxed text-[var(--color-ink-muted)]">
              {message ?? 'Diese Aktion kann nicht rückgängig gemacht werden.'}
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} autoFocus>
              Abbrechen
            </Button>
            <Button type="button" variant="danger" loading={isPending} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
