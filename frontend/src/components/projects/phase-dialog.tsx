'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { FieldError, Input, Label } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { fieldErrorsOf, validationToastMessage } from '@/lib/api/form-errors';
import {
  PHASE_STATUS_LABELS,
  useCreatePhase,
  useUpdatePhase,
  type PhaseStatus,
  type ProjectPhase,
} from '@/lib/api/projects';

const FIELD_LABELS: Record<string, string> = {
  name: 'Name',
  status: 'Status',
  start_date: 'Start',
  end_date: 'Ende',
  planned_hours: 'Geplante Stunden',
  order: 'Reihenfolge',
};

/** Create or edit a project phase. `nextOrder` seats a new phase at the end. */
export function PhaseFormDialog({
  open,
  onOpenChange,
  projectId,
  nextOrder,
  phase,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  nextOrder: number;
  phase?: ProjectPhase;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={phase ? 'Phase bearbeiten' : 'Neue Phase'}
        description="Grobe Projektabschnitte mit Zeitraum und Stundenplanung."
      >
        {/* State lives here: the content unmounts on close, so each opening
            starts from the passed-in phase without any reset effect. */}
        <PhaseForm
          key={phase?.id ?? 'new'}
          projectId={projectId}
          nextOrder={nextOrder}
          phase={phase}
          onClose={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function PhaseForm({
  projectId,
  nextOrder,
  phase,
  onClose,
}: {
  projectId: string;
  nextOrder: number;
  phase?: ProjectPhase;
  onClose: () => void;
}) {
  const isEdit = Boolean(phase);
  const createPhase = useCreatePhase();
  const updatePhase = useUpdatePhase();

  const [name, setName] = React.useState(phase?.name ?? '');
  const [status, setStatus] = React.useState<PhaseStatus>(phase?.status ?? 'planned');
  const [startDate, setStartDate] = React.useState(phase?.start_date ?? '');
  const [endDate, setEndDate] = React.useState(phase?.end_date ?? '');
  const [plannedHours, setPlannedHours] = React.useState(phase?.planned_hours ?? '');
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    if (startDate && endDate && endDate < startDate) {
      setErrors({ end_date: 'Ende darf nicht vor dem Start liegen.' });
      return;
    }
    const payload = {
      project: projectId,
      name: name.trim(),
      status,
      start_date: startDate || null,
      end_date: endDate || null,
      planned_hours: plannedHours || null,
      order: phase?.order ?? nextOrder,
    };
    const handleError = (error: unknown) => {
      const fieldErrors = fieldErrorsOf(error);
      if (fieldErrors) {
        setErrors(fieldErrors);
        toast.error(validationToastMessage(fieldErrors, FIELD_LABELS));
      } else {
        toast.error(error instanceof Error ? error.message : 'Speichern fehlgeschlagen.');
      }
    };
    if (isEdit && phase) {
      updatePhase.mutate(
        { id: phase.id, ...payload },
        {
          onSuccess: () => {
            toast.success('Phase gespeichert.');
            onClose();
          },
          onError: handleError,
        },
      );
    } else {
      createPhase.mutate(payload, {
        onSuccess: (created) => {
          toast.success(`Phase „${created.name}“ angelegt.`);
          onClose();
        },
        onError: handleError,
      });
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <Label htmlFor="phase-name" required>
          Name
        </Label>
        <Input
          id="phase-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="z. B. Konzeption"
          invalid={Boolean(errors.name)}
          autoFocus
          required
        />
        <FieldError>{errors.name}</FieldError>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="phase-status">Status</Label>
          <Select
            id="phase-status"
            value={status}
            onChange={(event) => setStatus(event.target.value as PhaseStatus)}
          >
            {Object.entries(PHASE_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="phase-hours">Geplante Stunden</Label>
          <Input
            id="phase-hours"
            type="number"
            step="0.5"
            min="0"
            placeholder="Optional"
            value={plannedHours}
            onChange={(event) => setPlannedHours(event.target.value)}
            invalid={Boolean(errors.planned_hours)}
          />
          <FieldError>{errors.planned_hours}</FieldError>
        </div>
        <div>
          <Label htmlFor="phase-start">Start</Label>
          <Input
            id="phase-start"
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
            invalid={Boolean(errors.start_date)}
          />
          <FieldError>{errors.start_date}</FieldError>
        </div>
        <div>
          <Label htmlFor="phase-end">Ende</Label>
          <Input
            id="phase-end"
            type="date"
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
            invalid={Boolean(errors.end_date)}
          />
          <FieldError>{errors.end_date}</FieldError>
        </div>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Abbrechen
        </Button>
        <Button
          type="submit"
          variant="primary"
          loading={createPhase.isPending || updatePhase.isPending}
        >
          {isEdit ? 'Speichern' : 'Anlegen'}
        </Button>
      </div>
    </form>
  );
}
