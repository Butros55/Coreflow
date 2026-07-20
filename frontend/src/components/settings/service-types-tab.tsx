'use client';

import { Plus, Trash2 } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { DeleteConfirmationDialog } from '@/components/ui/delete-confirmation-dialog';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { DataTable, Td, Th } from '@/components/ui/group-bar';
import { Input, Label } from '@/components/ui/input';
import { EmptyState, Panel } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import {
  useDeleteServiceType,
  useSaveServiceType,
  useServiceTypesAll,
  type ServiceType,
} from '@/lib/api/settings';
import { usePermissions } from '@/lib/session';
import { formatMoney } from '@/lib/utils';

export function ServiceTypesTab() {
  const { data } = useServiceTypesAll();
  const permissions = usePermissions();
  const remove = useDeleteServiceType();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [serviceToDelete, setServiceToDelete] = React.useState<ServiceType | null>(null);
  const services = data?.results ?? [];

  return (
    <div className="space-y-3">
      {permissions.can_manage_settings ? (
        <div className="flex justify-end">
          <Button variant="primary" size="sm" onClick={() => setDialogOpen(true)}>
            <Plus aria-hidden /> Leistungsart
          </Button>
        </div>
      ) : null}
      {services.length === 0 ? (
        <EmptyState
          title="Keine Leistungsarten"
          description="Leistungsarten (Entwicklung, Beratung …) bündeln Zeiten und Rechnungstexte."
        />
      ) : (
        <Panel>
          <DataTable>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Beschreibung</Th>
                <Th className="text-right">Stundensatz</Th>
                <Th>Status</Th>
                {permissions.can_manage_settings ? (
                  <Th className="w-10" aria-label="Aktion" />
                ) : null}
              </tr>
            </thead>
            <tbody>
              {services.map((service) => (
                <tr key={service.id} className="group last:[&>td]:border-b-0">
                  <Td className="font-medium">{service.name}</Td>
                  <Td className="text-[var(--color-ink-muted)]">{service.description || '—'}</Td>
                  <Td className="tabular text-right">
                    {service.default_hourly_rate ? formatMoney(service.default_hourly_rate) : '—'}
                  </Td>
                  <Td>
                    <StatusTint tone={service.active ? 'done' : 'hold'}>
                      {service.active ? 'Aktiv' : 'Inaktiv'}
                    </StatusTint>
                  </Td>
                  {permissions.can_manage_settings ? (
                    <Td className="text-right">
                      <button
                        type="button"
                        onClick={() => setServiceToDelete(service)}
                        aria-label="Löschen"
                        className="invisible rounded p-1 text-[var(--color-ink-subtle)] group-hover:visible hover:text-[var(--color-danger)]"
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                      </button>
                    </Td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Panel>
      )}
      <ServiceTypeDialog open={dialogOpen} onOpenChange={setDialogOpen} />
      <DeleteConfirmationDialog
        open={Boolean(serviceToDelete)}
        onOpenChange={(open) => !open && setServiceToDelete(null)}
        title="Leistungsart löschen?"
        itemName={serviceToDelete?.name ?? ''}
        message="Bestehende Zeiteinträge bleiben erhalten, verlieren aber die Zuordnung zu dieser Leistungsart."
        isPending={remove.isPending}
        onConfirm={() => {
          if (!serviceToDelete) return;
          remove.mutate(serviceToDelete.id, {
            onSuccess: () => {
              toast.success('Leistungsart gelöscht.');
              setServiceToDelete(null);
            },
            onError: (error) => toast.error(error.message),
          });
        }}
      />
    </div>
  );
}

function ServiceTypeDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const save = useSaveServiceType();
  const [name, setName] = React.useState('');
  const [rate, setRate] = React.useState('');
  const [description, setDescription] = React.useState('');

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    save.mutate(
      { name: name.trim(), default_hourly_rate: rate || null, description },
      {
        onSuccess: () => {
          toast.success('Leistungsart angelegt.');
          onOpenChange(false);
          setName('');
          setRate('');
          setDescription('');
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Neue Leistungsart">
        <form onSubmit={submit} className="space-y-3">
          <div>
            <Label htmlFor="st-name" required>
              Name
            </Label>
            <Input
              id="st-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              required
            />
          </div>
          <div>
            <Label htmlFor="st-rate">Stundensatz (€)</Label>
            <Input
              id="st-rate"
              type="number"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              placeholder="Workspace-Standard"
            />
          </div>
          <div>
            <Label htmlFor="st-desc">Beschreibung</Label>
            <Input
              id="st-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending}>
              Anlegen
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
