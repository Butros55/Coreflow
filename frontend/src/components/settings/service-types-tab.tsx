'use client';

import { Pencil, Plus, Trash2 } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { DeleteConfirmationDialog } from '@/components/ui/delete-confirmation-dialog';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { DataTable, Td, Th } from '@/components/ui/group-bar';
import { FieldError, Input, Label } from '@/components/ui/input';
import { EmptyState, Panel } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import { fieldErrorsOf, validationToastMessage } from '@/lib/api/form-errors';
import {
  useApplyServiceTypeRate,
  useDeleteServiceType,
  useSaveServiceType,
  useServiceTypesAll,
  type ServiceType,
} from '@/lib/api/settings';
import { usePermissions } from '@/lib/session';
import { cn, formatMoney } from '@/lib/utils';

export function ServiceTypesTab() {
  const { data } = useServiceTypesAll();
  const permissions = usePermissions();
  const remove = useDeleteServiceType();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [serviceToEdit, setServiceToEdit] = React.useState<ServiceType | null>(null);
  const [serviceToDelete, setServiceToDelete] = React.useState<ServiceType | null>(null);
  const services = data?.results ?? [];

  const openEdit = (service: ServiceType) => {
    setServiceToEdit(service);
    setDialogOpen(true);
  };
  const openCreate = () => {
    setServiceToEdit(null);
    setDialogOpen(true);
  };

  return (
    <div className="space-y-3">
      {permissions.can_manage_settings ? (
        <div className="flex justify-end">
          <Button variant="primary" size="sm" onClick={openCreate}>
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
                  <Th className="w-16" aria-label="Aktionen" />
                ) : null}
              </tr>
            </thead>
            <tbody>
              {services.map((service) => (
                <tr
                  key={service.id}
                  className={cn(
                    'group last:[&>td]:border-b-0',
                    permissions.can_manage_settings &&
                      'cursor-pointer transition-colors hover:bg-[var(--color-panel-raised)]',
                  )}
                  onClick={permissions.can_manage_settings ? () => openEdit(service) : undefined}
                >
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
                      <div className="invisible flex items-center justify-end gap-1 group-hover:visible">
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            openEdit(service);
                          }}
                          aria-label="Bearbeiten"
                          className="rounded-full p-1 text-[var(--color-ink-subtle)] hover:bg-[var(--color-brand-subtle)] hover:text-[var(--color-brand)]"
                        >
                          <Pencil className="size-3.5" aria-hidden />
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            setServiceToDelete(service);
                          }}
                          aria-label="Löschen"
                          className="rounded-full p-1 text-[var(--color-ink-subtle)] hover:bg-[var(--color-danger-soft)] hover:text-[var(--color-danger)]"
                        >
                          <Trash2 className="size-3.5" aria-hidden />
                        </button>
                      </div>
                    </Td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Panel>
      )}
      <ServiceTypeDialog
        key={serviceToEdit?.id ?? 'create'}
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) setServiceToEdit(null);
        }}
        service={serviceToEdit}
      />
      <DeleteConfirmationDialog
        open={Boolean(serviceToDelete)}
        onOpenChange={(open) => !open && setServiceToDelete(null)}
        title="Leistungsart löschen?"
        itemName={serviceToDelete?.name ?? ''}
        message="Bestehende Zeiteinträge bleiben erhalten, verlieren aber die Zuordnung zu dieser Leistungsart. Tipp: Deaktivieren statt löschen behält die Historie."
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

const DIALOG_LABELS: Record<string, string> = {
  name: 'Name',
  default_hourly_rate: 'Stundensatz (€)',
  description: 'Beschreibung',
};

function ServiceTypeDialog({
  open,
  onOpenChange,
  service,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  service: ServiceType | null;
}) {
  const save = useSaveServiceType();
  const applyRate = useApplyServiceTypeRate();
  const isEdit = service !== null;

  const [name, setName] = React.useState(service?.name ?? '');
  const [rate, setRate] = React.useState(service?.default_hourly_rate ?? '');
  const [description, setDescription] = React.useState(service?.description ?? '');
  const [active, setActive] = React.useState(service?.active ?? true);
  const [applyToOpen, setApplyToOpen] = React.useState(true);
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  const rateChanged = isEdit && (service.default_hourly_rate ?? '') !== rate;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setErrors({ name: 'Bitte einen Namen angeben.' });
      return;
    }
    save.mutate(
      {
        id: service?.id,
        name: name.trim(),
        default_hourly_rate: rate || null,
        description,
        active,
      },
      {
        onSuccess: (saved) => {
          if (isEdit && rateChanged && applyToOpen) {
            applyRate.mutate(saved.id, {
              onSuccess: (result) =>
                toast.success(
                  result.updated > 0
                    ? `Gespeichert — ${result.updated} offene Zeiteinträge neu berechnet.`
                    : 'Gespeichert — keine offenen Zeiteinträge betroffen.',
                ),
              onError: () => toast.error('Gespeichert, aber Neuberechnung fehlgeschlagen.'),
            });
          } else {
            toast.success(isEdit ? 'Leistungsart gespeichert.' : 'Leistungsart angelegt.');
          }
          onOpenChange(false);
        },
        onError: (error) => {
          const fieldErrors = fieldErrorsOf(error);
          if (fieldErrors) {
            setErrors(fieldErrors);
            toast.error(validationToastMessage(fieldErrors, DIALOG_LABELS));
          } else {
            toast.error(error.message);
          }
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={isEdit ? `Leistungsart bearbeiten` : 'Neue Leistungsart'}>
        <form onSubmit={submit} className="space-y-3" noValidate>
          <div>
            <Label htmlFor="st-name" required>
              Name
            </Label>
            <Input
              id="st-name"
              value={name}
              invalid={Boolean(errors.name)}
              onChange={(e) => {
                setName(e.target.value);
                setErrors((p) => (p.name ? { ...p, name: '' } : p));
              }}
              autoFocus
              required
            />
            <FieldError>{errors.name}</FieldError>
          </div>
          <div>
            <Label htmlFor="st-rate">Stundensatz (€)</Label>
            <Input
              id="st-rate"
              type="number"
              step="0.01"
              min="0"
              value={rate ?? ''}
              invalid={Boolean(errors.default_hourly_rate)}
              onChange={(e) => {
                setRate(e.target.value);
                setErrors((p) => (p.default_hourly_rate ? { ...p, default_hourly_rate: '' } : p));
              }}
              placeholder="Workspace-Standard"
            />
            <FieldError>{errors.default_hourly_rate}</FieldError>
          </div>
          <div>
            <Label htmlFor="st-desc">Beschreibung</Label>
            <Input
              id="st-desc"
              value={description}
              invalid={Boolean(errors.description)}
              onChange={(e) => setDescription(e.target.value)}
            />
            <FieldError>{errors.description}</FieldError>
          </div>

          {isEdit ? (
            <label className="flex cursor-pointer items-center gap-2 text-[length:var(--text-sm)]">
              <input
                type="checkbox"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
                className="size-4 accent-[var(--color-brand)]"
              />
              Aktiv — in Auswahlfeldern anbieten
            </label>
          ) : null}

          {rateChanged ? (
            <label className="flex cursor-pointer items-start gap-2 rounded-[var(--radius-md)] bg-[var(--color-brand-subtle)] p-3 text-[length:var(--text-xs)]">
              <input
                type="checkbox"
                checked={applyToOpen}
                onChange={(e) => setApplyToOpen(e.target.checked)}
                className="mt-0.5 size-4 shrink-0 accent-[var(--color-brand)]"
              />
              <span>
                <span className="font-medium">
                  Neuen Stundensatz auf offene Zeiteinträge anwenden.
                </span>{' '}
                Noch nicht abgerechnete Zeiten dieser Leistungsart werden neu bewertet —
                abgerechnete und in Rechnungsentwürfen gebundene Zeiten bleiben unverändert.
                Speziellere Sätze (Projekt/Kunde) haben weiterhin Vorrang.
              </span>
            </label>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending}>
              {isEdit ? 'Speichern' : 'Anlegen'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
