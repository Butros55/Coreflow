'use client';

import { useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { FieldError, Input, Label, Textarea } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { useClients } from '@/lib/api/crm';
import { fieldErrorsOf, validationToastMessage } from '@/lib/api/form-errors';
import {
  BILLING_MODEL_LABELS,
  PRIORITY_LABELS,
  PROJECT_STATUS_LABELS,
  useCreateProject,
  useUpdateProject,
  type BillingModel,
  type Priority,
  type Project,
  type ProjectPayload,
  type ProjectStatus,
} from '@/lib/api/projects';
import { useMembers } from '@/lib/api/settings';
import { useSession } from '@/lib/session';

const FIELD_LABELS: Record<string, string> = {
  name: 'Projektname',
  client: 'Kunde',
  status: 'Status',
  priority: 'Priorität',
  billing_model: 'Abrechnungsmodell',
  default_hourly_rate: 'Stundensatz',
  budget_hours: 'Stundenbudget',
  budget_amount: 'Kostenbudget',
  start_date: 'Start',
  target_date: 'Zieldatum',
  lead_id: 'Projektleitung',
  description: 'Beschreibung',
  color: 'Farbe',
  progress: 'Fortschritt',
};

/** Preset palette: enough contrast on both themes, plus "no colour". */
const COLOR_PRESETS = [
  '#4f7dff',
  '#7c5cff',
  '#00a3a3',
  '#2e9e44',
  '#e08700',
  '#e05252',
  '#d94f9e',
  '#6b7a90',
];

interface FormState {
  name: string;
  client: string;
  status: ProjectStatus;
  priority: Priority;
  billingModel: BillingModel;
  hourlyRate: string;
  budgetHours: string;
  budgetAmount: string;
  startDate: string;
  targetDate: string;
  leadId: string;
  description: string;
  color: string;
  progress: string;
}

function initialState(project?: Project): FormState {
  return {
    name: project?.name ?? '',
    client: project?.client ?? '',
    status: project?.status ?? 'active',
    priority: project?.priority ?? 'medium',
    billingModel: project?.billing_model ?? 'hourly',
    hourlyRate: project?.default_hourly_rate ?? '',
    budgetHours: project?.budget_hours ?? '',
    budgetAmount: project?.budget_amount ?? '',
    startDate: project?.start_date ?? '',
    targetDate: project?.target_date ?? '',
    leadId: project?.lead?.id ?? '',
    description: project?.description ?? '',
    color: project?.color ?? '',
    progress: project ? String(project.progress) : '0',
  };
}

/**
 * One dialog for both directions: without `project` it creates (and routes to
 * the new detail page), with `project` it edits in place. Every writable
 * project field is here — budgets, billing model, rate, dates, lead.
 */
export function ProjectFormDialog({
  open,
  onOpenChange,
  project,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  project?: Project;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        wide
        title={project ? 'Projekt bearbeiten' : 'Neues Projekt'}
        description={
          project
            ? 'Stammdaten, Budgets und Abrechnung anpassen.'
            : 'Ein Hauptboard wird automatisch mit angelegt.'
        }
      >
        {/* State lives here: the content unmounts on close, so each opening
            starts from the passed-in project without any reset effect. */}
        <ProjectForm
          key={project?.id ?? 'new'}
          project={project}
          onClose={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function ProjectForm({ project, onClose }: { project?: Project; onClose: () => void }) {
  const router = useRouter();
  const isEdit = Boolean(project);
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const { data: session } = useSession();
  const { data: memberships } = useMembers(session?.workspace?.id);
  const members = (memberships ?? []).filter((membership) => membership.is_active);
  const { data: clientsData } = useClients({ archived: false });
  const clients = clientsData?.results ?? [];

  const [form, setForm] = React.useState<FormState>(() => initialState(project));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const isPending = createProject.isPending || updateProject.isPending;

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((previous) => ({ ...previous, [key]: value }));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.name.trim() || !form.client) return;
    const payload: ProjectPayload = {
      name: form.name.trim(),
      client: form.client,
      status: form.status,
      priority: form.priority,
      billing_model: form.billingModel,
      default_hourly_rate: form.hourlyRate || null,
      budget_hours: form.budgetHours || null,
      budget_amount: form.budgetAmount || null,
      start_date: form.startDate || null,
      target_date: form.targetDate || null,
      lead_id: form.leadId || null,
      description: form.description,
      color: form.color,
    };
    if (isEdit) payload.progress = Math.min(100, Math.max(0, Number(form.progress) || 0));

    const handleError = (error: unknown) => {
      const fieldErrors = fieldErrorsOf(error);
      if (fieldErrors) {
        setErrors(fieldErrors);
        toast.error(validationToastMessage(fieldErrors, FIELD_LABELS));
      } else {
        toast.error(error instanceof Error ? error.message : 'Speichern fehlgeschlagen.');
      }
    };

    if (isEdit && project) {
      updateProject.mutate(
        { id: project.id, ...payload },
        {
          onSuccess: () => {
            toast.success('Projekt gespeichert.');
            onClose();
          },
          onError: handleError,
        },
      );
    } else {
      createProject.mutate(payload, {
        onSuccess: (created) => {
          toast.success(`Projekt „${created.name}“ angelegt.`);
          onClose();
          router.push(`/projects/${created.id}`);
        },
        onError: handleError,
      });
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="project-name" required>
            Projektname
          </Label>
          <Input
            id="project-name"
            value={form.name}
            onChange={(event) => set('name', event.target.value)}
            invalid={Boolean(errors.name)}
            autoFocus={!isEdit}
            required
          />
          <FieldError>{errors.name}</FieldError>
        </div>
        <div>
          <Label htmlFor="project-client" required>
            Kunde
          </Label>
          <Select
            id="project-client"
            value={form.client}
            onChange={(event) => set('client', event.target.value)}
            invalid={Boolean(errors.client)}
            required
          >
            <option value="" disabled>
              Kunde wählen…
            </option>
            {clients.map((client) => (
              <option key={client.id} value={client.id}>
                {client.name}
              </option>
            ))}
          </Select>
          <FieldError>{errors.client}</FieldError>
        </div>
        <div>
          <Label htmlFor="project-status">Status</Label>
          <Select
            id="project-status"
            value={form.status}
            onChange={(event) => set('status', event.target.value as ProjectStatus)}
          >
            {Object.entries(PROJECT_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="project-priority">Priorität</Label>
          <Select
            id="project-priority"
            value={form.priority}
            onChange={(event) => set('priority', event.target.value as Priority)}
          >
            {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="project-start">Start</Label>
          <Input
            id="project-start"
            type="date"
            value={form.startDate}
            onChange={(event) => set('startDate', event.target.value)}
            invalid={Boolean(errors.start_date)}
          />
          <FieldError>{errors.start_date}</FieldError>
        </div>
        <div>
          <Label htmlFor="project-target">Zieldatum</Label>
          <Input
            id="project-target"
            type="date"
            value={form.targetDate}
            onChange={(event) => set('targetDate', event.target.value)}
            invalid={Boolean(errors.target_date)}
          />
          <FieldError>{errors.target_date}</FieldError>
        </div>
        <div>
          <Label htmlFor="project-billing">Abrechnungsmodell</Label>
          <Select
            id="project-billing"
            value={form.billingModel}
            onChange={(event) => set('billingModel', event.target.value as BillingModel)}
          >
            {Object.entries(BILLING_MODEL_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="project-lead">Projektleitung</Label>
          <Select
            id="project-lead"
            value={form.leadId}
            onChange={(event) => set('leadId', event.target.value)}
          >
            <option value="">Keine</option>
            {members.map(({ user }) => (
              <option key={user.id} value={user.id}>
                {user.full_name || user.email}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="project-rate">Stundensatz (€)</Label>
          <Input
            id="project-rate"
            type="number"
            step="0.01"
            min="0"
            placeholder="Kunden-/Workspace-Standard"
            value={form.hourlyRate}
            onChange={(event) => set('hourlyRate', event.target.value)}
            invalid={Boolean(errors.default_hourly_rate)}
          />
          <FieldError>{errors.default_hourly_rate}</FieldError>
        </div>
        {isEdit ? (
          <div>
            <Label htmlFor="project-progress">Fortschritt (%)</Label>
            <Input
              id="project-progress"
              type="number"
              min="0"
              max="100"
              step="1"
              value={form.progress}
              onChange={(event) => set('progress', event.target.value)}
              invalid={Boolean(errors.progress)}
            />
            <FieldError>{errors.progress}</FieldError>
          </div>
        ) : (
          <div />
        )}
        <div>
          <Label htmlFor="project-budget-hours">Stundenbudget (h)</Label>
          <Input
            id="project-budget-hours"
            type="number"
            step="0.25"
            min="0"
            placeholder="Ohne Limit"
            value={form.budgetHours}
            onChange={(event) => set('budgetHours', event.target.value)}
            invalid={Boolean(errors.budget_hours)}
          />
          <FieldError>{errors.budget_hours}</FieldError>
        </div>
        <div>
          <Label htmlFor="project-budget-amount">Kostenbudget (€)</Label>
          <Input
            id="project-budget-amount"
            type="number"
            step="0.01"
            min="0"
            placeholder="Ohne Limit"
            value={form.budgetAmount}
            onChange={(event) => set('budgetAmount', event.target.value)}
            invalid={Boolean(errors.budget_amount)}
          />
          <FieldError>{errors.budget_amount}</FieldError>
        </div>
      </div>

      <div>
        <Label>Farbe</Label>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => set('color', '')}
            aria-label="Keine Farbe"
            aria-pressed={form.color === ''}
            className={`flex h-6 items-center rounded-full border px-2 text-[length:var(--text-2xs)] transition-colors ${
              form.color === ''
                ? 'border-[var(--color-brand)] text-[var(--color-ink)]'
                : 'border-[var(--color-line)] text-[var(--color-ink-subtle)] hover:border-[var(--color-line-strong)]'
            }`}
          >
            Ohne
          </button>
          {COLOR_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => set('color', preset)}
              aria-label={`Farbe ${preset}`}
              aria-pressed={form.color === preset}
              className="flex size-6 items-center justify-center rounded-full border-2 transition-transform hover:scale-110"
              style={{
                backgroundColor: preset,
                borderColor: form.color === preset ? 'var(--color-ink)' : 'transparent',
              }}
            />
          ))}
        </div>
      </div>

      <div>
        <Label htmlFor="project-description">Beschreibung</Label>
        <Textarea
          id="project-description"
          value={form.description}
          placeholder="Worum geht es in diesem Projekt?"
          onChange={(event) => set('description', event.target.value)}
        />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Abbrechen
        </Button>
        <Button type="submit" variant="primary" loading={isPending}>
          {isEdit ? 'Speichern' : 'Anlegen'}
        </Button>
      </div>
    </form>
  );
}
