'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { FieldError, Input, Label } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { fieldErrorsOf, validationToastMessage } from '@/lib/api/form-errors';
import {
  SPRINT_STATUS_LABELS,
  useCreateSprint,
  useUpdateSprint,
  type Sprint,
  type SprintStatus,
} from '@/lib/api/projects';

const FIELD_LABELS: Record<string, string> = {
  name: 'Name',
  goal: 'Sprintziel',
  start_date: 'Start',
  end_date: 'Ende',
  status: 'Status',
  capacity_hours: 'Kapazität',
};

/** Create or edit a sprint; the project (and default board) is fixed. */
export function SprintFormDialog({
  open,
  onOpenChange,
  projectId,
  boardId,
  sprint,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  boardId: string | null;
  sprint?: Sprint;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={sprint ? 'Sprint bearbeiten' : 'Neuer Sprint'}
        description="Zeitraum und Ziel festlegen — Aufgaben lassen sich anschließend zuordnen."
      >
        {/* State lives here: the content unmounts on close, so each opening
            starts from the passed-in sprint without any reset effect. */}
        <SprintForm
          key={sprint?.id ?? 'new'}
          projectId={projectId}
          boardId={boardId}
          sprint={sprint}
          onClose={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function SprintForm({
  projectId,
  boardId,
  sprint,
  onClose,
}: {
  projectId: string;
  boardId: string | null;
  sprint?: Sprint;
  onClose: () => void;
}) {
  const isEdit = Boolean(sprint);
  const createSprint = useCreateSprint();
  const updateSprint = useUpdateSprint();

  const [name, setName] = React.useState(sprint?.name ?? '');
  const [goal, setGoal] = React.useState(sprint?.goal ?? '');
  const [startDate, setStartDate] = React.useState(sprint?.start_date ?? '');
  const [endDate, setEndDate] = React.useState(sprint?.end_date ?? '');
  const [status, setStatus] = React.useState<SprintStatus>(sprint?.status ?? 'planned');
  const [capacity, setCapacity] = React.useState(sprint?.capacity_hours ?? '');
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
      board: boardId,
      name: name.trim(),
      goal: goal.trim(),
      start_date: startDate || null,
      end_date: endDate || null,
      status,
      capacity_hours: capacity || null,
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
    if (isEdit && sprint) {
      updateSprint.mutate(
        { id: sprint.id, ...payload },
        {
          onSuccess: () => {
            toast.success('Sprint gespeichert.');
            onClose();
          },
          onError: handleError,
        },
      );
    } else {
      createSprint.mutate(payload, {
        onSuccess: (created) => {
          toast.success(`Sprint „${created.name}“ angelegt.`);
          onClose();
        },
        onError: handleError,
      });
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <Label htmlFor="sprint-name" required>
          Name
        </Label>
        <Input
          id="sprint-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="z. B. Sprint 5"
          invalid={Boolean(errors.name)}
          autoFocus
          required
        />
        <FieldError>{errors.name}</FieldError>
      </div>
      <div>
        <Label htmlFor="sprint-goal">Sprintziel</Label>
        <Input
          id="sprint-goal"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="Was soll am Ende stehen?"
          invalid={Boolean(errors.goal)}
        />
        <FieldError>{errors.goal}</FieldError>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="sprint-start">Start</Label>
          <Input
            id="sprint-start"
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
            invalid={Boolean(errors.start_date)}
          />
          <FieldError>{errors.start_date}</FieldError>
        </div>
        <div>
          <Label htmlFor="sprint-end">Ende</Label>
          <Input
            id="sprint-end"
            type="date"
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
            invalid={Boolean(errors.end_date)}
          />
          <FieldError>{errors.end_date}</FieldError>
        </div>
        <div>
          <Label htmlFor="sprint-status">Status</Label>
          <Select
            id="sprint-status"
            value={status}
            onChange={(event) => setStatus(event.target.value as SprintStatus)}
          >
            {Object.entries(SPRINT_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="sprint-capacity">Kapazität (h)</Label>
          <Input
            id="sprint-capacity"
            type="number"
            step="0.5"
            min="0"
            placeholder="Optional"
            value={capacity}
            onChange={(event) => setCapacity(event.target.value)}
            invalid={Boolean(errors.capacity_hours)}
          />
          <FieldError>{errors.capacity_hours}</FieldError>
        </div>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Abbrechen
        </Button>
        <Button
          type="submit"
          variant="primary"
          loading={createSprint.isPending || updateSprint.isPending}
        >
          {isEdit ? 'Speichern' : 'Anlegen'}
        </Button>
      </div>
    </form>
  );
}
