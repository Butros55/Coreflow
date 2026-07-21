'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { FieldError, Input, Label } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { fieldErrorsOf, validationToastMessage } from '@/lib/api/form-errors';
import {
  PRIORITY_LABELS,
  TASK_STATUS_LABELS,
  TASK_STATUS_ORDER,
  useCreateTask,
  useProject,
  useSprints,
  type Priority,
  type TaskStatus,
} from '@/lib/api/projects';

const FIELD_LABELS: Record<string, string> = {
  title: 'Titel',
  status: 'Spalte',
  priority: 'Priorität',
  due_date: 'Fällig am',
  estimated_hours: 'Geschätzt',
  sprint: 'Sprint',
  phase: 'Phase',
};

/**
 * Create a task anywhere a project is known: the project and its board (and
 * thus the client) are wired automatically; sprint/phase are offered when the
 * project has any.
 */
export function CreateTaskDialog({
  open,
  onOpenChange,
  projectId,
  boardId,
  defaultSprint = null,
  defaultPhase = null,
  defaultStatus = 'todo',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  boardId: string;
  defaultSprint?: string | null;
  defaultPhase?: string | null;
  defaultStatus?: TaskStatus;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Neue Aufgabe">
        {/* State lives here: the content unmounts on close, so each opening
            starts fresh with the passed-in defaults — no reset effect. */}
        <CreateTaskForm
          projectId={projectId}
          boardId={boardId}
          defaultSprint={defaultSprint}
          defaultPhase={defaultPhase}
          defaultStatus={defaultStatus}
          onClose={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function CreateTaskForm({
  projectId,
  boardId,
  defaultSprint,
  defaultPhase,
  defaultStatus,
  onClose,
}: {
  projectId: string;
  boardId: string;
  defaultSprint: string | null;
  defaultPhase: string | null;
  defaultStatus: TaskStatus;
  onClose: () => void;
}) {
  const createTask = useCreateTask();
  // Sprint/phase pickers feed from the project — only rendered when present.
  const { data: project } = useProject(projectId);
  const { data: sprintsData } = useSprints(projectId);
  const sprints = (sprintsData?.results ?? []).filter((sprint) => sprint.status !== 'completed');
  const phases = project?.phases ?? [];

  const [title, setTitle] = React.useState('');
  const [status, setStatus] = React.useState<TaskStatus>(defaultStatus);
  const [priority, setPriority] = React.useState<Priority>('medium');
  const [dueDate, setDueDate] = React.useState('');
  const [estimatedHours, setEstimatedHours] = React.useState('');
  const [sprint, setSprint] = React.useState<string>(defaultSprint ?? '');
  const [phase, setPhase] = React.useState<string>(defaultPhase ?? '');
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    createTask.mutate(
      {
        title: title.trim(),
        status,
        priority,
        board: boardId,
        project: projectId,
        due_date: dueDate || null,
        estimated_hours: estimatedHours || null,
        sprint: sprint || null,
        phase: phase || null,
      },
      {
        onSuccess: (task) => {
          toast.success(`Aufgabe „${task.title}“ angelegt.`);
          onClose();
        },
        onError: (error) => {
          const fieldErrors = fieldErrorsOf(error);
          if (fieldErrors) {
            setErrors(fieldErrors);
            toast.error(validationToastMessage(fieldErrors, FIELD_LABELS));
          } else {
            toast.error(error.message);
          }
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      {project ? (
        <p className="text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
          Wird automatisch {project.client_name} · {project.name} zugeordnet.
        </p>
      ) : null}
      <div>
        <Label htmlFor="task-title" required>
          Titel
        </Label>
        <Input
          id="task-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          invalid={Boolean(errors.title)}
          autoFocus
          required
        />
        <FieldError>{errors.title}</FieldError>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="task-status">Spalte</Label>
          <Select
            id="task-status"
            value={status}
            onChange={(event) => setStatus(event.target.value as TaskStatus)}
          >
            {TASK_STATUS_ORDER.map((value) => (
              <option key={value} value={value}>
                {TASK_STATUS_LABELS[value]}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="task-priority">Priorität</Label>
          <Select
            id="task-priority"
            value={priority}
            onChange={(event) => setPriority(event.target.value as Priority)}
          >
            {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="task-due">Fällig am</Label>
          <Input
            id="task-due"
            type="date"
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
            invalid={Boolean(errors.due_date)}
          />
          <FieldError>{errors.due_date}</FieldError>
        </div>
        <div>
          <Label htmlFor="task-estimate">Geschätzt (h)</Label>
          <Input
            id="task-estimate"
            type="number"
            step="0.25"
            min="0"
            value={estimatedHours}
            onChange={(event) => setEstimatedHours(event.target.value)}
            invalid={Boolean(errors.estimated_hours)}
          />
          <FieldError>{errors.estimated_hours}</FieldError>
        </div>
        {sprints.length > 0 ? (
          <div>
            <Label htmlFor="task-sprint">Sprint</Label>
            <Select
              id="task-sprint"
              value={sprint}
              onChange={(event) => setSprint(event.target.value)}
            >
              <option value="">Backlog</option>
              {sprints.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          </div>
        ) : null}
        {phases.length > 0 ? (
          <div>
            <Label htmlFor="task-phase">Phase</Label>
            <Select
              id="task-phase"
              value={phase}
              onChange={(event) => setPhase(event.target.value)}
            >
              <option value="">Keine Phase</option>
              {phases.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          </div>
        ) : null}
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Abbrechen
        </Button>
        <Button type="submit" variant="primary" loading={createTask.isPending}>
          Anlegen
        </Button>
      </div>
    </form>
  );
}
