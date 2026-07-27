'use client';

import { Building2 } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Input, Label } from '@/components/ui/input';
import { useCreateWorkspace } from '@/lib/session';

/** Shared form: used by the switcher dialog and the no-workspace onboarding. */
function CreateWorkspaceForm({ onDone }: { onDone?: () => void }) {
  const create = useCreateWorkspace();
  const [name, setName] = React.useState('');
  const [smallBusiness, setSmallBusiness] = React.useState(false);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), small_business: smallBusiness },
      {
        onSuccess: () => {
          toast.success(`Workspace „${name.trim()}“ erstellt.`);
          onDone?.();
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <Label htmlFor="ws-create-name" required>
          Name des Workspace
        </Label>
        <Input
          id="ws-create-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="z. B. Meine Firma"
          autoFocus
          required
        />
      </div>
      <label className="flex items-center gap-2 text-[length:var(--text-sm)]">
        <input
          type="checkbox"
          checked={smallBusiness}
          onChange={(e) => setSmallBusiness(e.target.checked)}
          className="size-3.5 accent-[var(--color-brand)]"
        />
        Kleinunternehmer nach §19 UStG (Rechnungen ohne USt)
      </label>
      <p className="text-[length:var(--text-2xs)] leading-relaxed text-[var(--color-ink-subtle)]">
        Alle Daten — Kunden, Projekte, Zeiten, Rechnungen — sind strikt pro Workspace getrennt.
        Firmendaten und Steuerprofil vervollständigst du danach unter Einstellungen.
      </p>
      <div className="flex justify-end pt-1">
        <Button type="submit" variant="primary" loading={create.isPending}>
          Workspace erstellen
        </Button>
      </div>
    </form>
  );
}

export function CreateWorkspaceDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Neuer Workspace">
        <CreateWorkspaceForm onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

/** Full-screen onboarding for an account that has no workspace at all. */
export function WorkspaceOnboarding() {
  return (
    <div className="flex h-dvh items-center justify-center bg-[var(--color-canvas)] p-4">
      <div className="w-full max-w-md rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-panel)] p-6">
        <div className="mb-4 flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--color-brand-subtle)]">
            <Building2 className="size-4.5 text-[var(--color-brand)]" aria-hidden />
          </span>
          <div>
            <h1 className="text-[length:var(--text-lg)] font-semibold">Willkommen bei Coreflow</h1>
            <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
              Erstelle deinen ersten Workspace, um loszulegen.
            </p>
          </div>
        </div>
        <CreateWorkspaceForm />
      </div>
    </div>
  );
}
