'use client';

import { Loader2, Play, Plus, Trash2, X } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { STATUS_TONES, StatusSelect } from '@/components/tasks/status-select';
import { Avatar } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Input, Label, Textarea } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { StatusPill } from '@/components/ui/status-pill';
import {
  PRIORITY_LABELS,
  useAddComment,
  useChecklist,
  useChecklistMutations,
  useSprints,
  useTask,
  useTaskComments,
  useUpdateTask,
  type Priority,
  type Task,
} from '@/lib/api/projects';
import { useStartTimer, useTimer } from '@/lib/api/time';
import { usePermissions } from '@/lib/session';
import { cn, formatHours } from '@/lib/utils';

/**
 * Right-hand task detail drawer (reference: the Plaky item card).
 *
 * The open task lives in the URL (?task=<id>) — handled by the page — so a
 * drawer state is linkable and survives reload.
 */
export function TaskDrawer({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const { data: task, isLoading } = useTask(taskId);
  const updateTask = useUpdateTask();
  const permissions = usePermissions();
  const canEdit = permissions.can_write;

  // Escape closes, matching every other overlay in the app.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const patch = (fields: Partial<Omit<Task, 'id'>>) =>
    updateTask.mutate(
      { id: taskId, ...fields },
      { onError: () => toast.error('Änderung konnte nicht gespeichert werden.') },
    );

  return (
    <aside
      className="flex h-full w-[var(--spacing-drawer)] max-w-full shrink-0 flex-col border-l border-[var(--color-line)] bg-[var(--color-panel)] shadow-[var(--shadow-drawer)]"
      aria-label="Aufgabendetails"
    >
      {isLoading || !task ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2
            className="size-5 animate-spin text-[var(--color-ink-subtle)]"
            aria-label="Lädt"
          />
        </div>
      ) : (
        <>
          <header className="flex items-start gap-2 border-b border-[var(--color-line)] p-4">
            <div className="min-w-0 flex-1">
              <div className="mb-1 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                {task.client_name} · {task.project_name}
                {task.sprint_name ? ` · ${task.sprint_name}` : ''}
              </div>
              <EditableTitle
                key={task.id + task.title}
                title={task.title}
                disabled={!canEdit}
                onSave={(title) => patch({ title })}
              />
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Schließen"
              className="rounded-[var(--radius-xs)] p-1 text-[var(--color-ink-subtle)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)]"
            >
              <X className="size-4" aria-hidden />
            </button>
          </header>

          <div className="flex-1 overflow-y-auto p-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Status</Label>
                <StatusSelect taskId={task.id} status={task.status} disabled={!canEdit} />
              </div>
              <div>
                <Label htmlFor="drawer-priority">Priorität</Label>
                <Select
                  id="drawer-priority"
                  value={task.priority}
                  disabled={!canEdit}
                  onChange={(event) => patch({ priority: event.target.value as Priority })}
                >
                  {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="drawer-due">Fällig am</Label>
                <Input
                  id="drawer-due"
                  type="date"
                  defaultValue={task.due_date ?? ''}
                  disabled={!canEdit}
                  onBlur={(event) => {
                    const value = event.target.value || null;
                    if (value !== task.due_date) patch({ due_date: value });
                  }}
                />
              </div>
              <div>
                <Label htmlFor="drawer-estimate">Geschätzt (h)</Label>
                <Input
                  id="drawer-estimate"
                  type="number"
                  step="0.25"
                  min="0"
                  defaultValue={task.estimated_hours ?? ''}
                  disabled={!canEdit}
                  onBlur={(event) => {
                    const value = event.target.value || null;
                    if (value !== task.estimated_hours) patch({ estimated_hours: value });
                  }}
                />
              </div>
              <SprintField
                projectId={task.project}
                value={task.sprint}
                disabled={!canEdit}
                onChange={(sprint) => patch({ sprint })}
              />
              <div>
                <Label>Erfasste Zeit</Label>
                <div className="flex h-8 items-center gap-2">
                  <span className="tabular text-[length:var(--text-sm)]">
                    {formatHours(task.logged_seconds / 3600)}
                  </span>
                  <QuickStartTimer taskId={task.id} disabled={!canEdit} />
                </div>
              </div>
            </div>

            <div className="mt-4">
              <Label htmlFor="drawer-description">Beschreibung</Label>
              <EditableDescription
                key={task.id + task.description}
                value={task.description}
                disabled={!canEdit}
                onSave={(description) => patch({ description })}
              />
            </div>

            {task.assignee_details.length > 0 ? (
              <div className="mt-4">
                <Label>Verantwortlich</Label>
                <div className="flex flex-wrap items-center gap-2">
                  {task.assignee_details.map((user) => (
                    <span
                      key={user.id}
                      className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-panel-raised)] py-0.5 pr-2 pl-0.5 text-[length:var(--text-xs)]"
                    >
                      <Avatar user={user} size="sm" />
                      {user.full_name}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            <ChecklistSection taskId={task.id} canEdit={canEdit} />
            <CommentsSection taskId={task.id} canEdit={canEdit} />
          </div>
        </>
      )}
    </aside>
  );
}

function EditableTitle({
  title,
  onSave,
  disabled,
}: {
  title: string;
  onSave: (title: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = React.useState(title);
  return (
    <input
      value={value}
      disabled={disabled}
      onChange={(event) => setValue(event.target.value)}
      onBlur={() => {
        const trimmed = value.trim();
        if (trimmed && trimmed !== title) onSave(trimmed);
        else setValue(title);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') (event.target as HTMLInputElement).blur();
      }}
      className="w-full bg-transparent text-[length:var(--text-lg)] font-semibold outline-none focus:rounded-[var(--radius-xs)] focus:ring-2 focus:ring-[var(--color-brand-ring)]"
      aria-label="Titel bearbeiten"
    />
  );
}

function EditableDescription({
  value: initial,
  onSave,
  disabled,
}: {
  value: string;
  onSave: (value: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = React.useState(initial);
  return (
    <Textarea
      id="drawer-description"
      value={value}
      disabled={disabled}
      placeholder="Keine Beschreibung"
      onChange={(event) => setValue(event.target.value)}
      onBlur={() => {
        if (value !== initial) onSave(value);
      }}
    />
  );
}

function SprintField({
  projectId,
  value,
  onChange,
  disabled,
}: {
  projectId: string;
  value: string | null;
  onChange: (sprint: string | null) => void;
  disabled: boolean;
}) {
  const { data } = useSprints(projectId);
  const sprints = data?.results ?? [];
  if (sprints.length === 0) return null;
  return (
    <div>
      <Label htmlFor="drawer-sprint">Sprint</Label>
      <Select
        id="drawer-sprint"
        value={value ?? ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">Backlog</option>
        {sprints.map((sprint) => (
          <option key={sprint.id} value={sprint.id}>
            {sprint.name}
          </option>
        ))}
      </Select>
    </div>
  );
}

function QuickStartTimer({ taskId, disabled }: { taskId: string; disabled: boolean }) {
  const { data } = useTimer();
  const startTimer = useStartTimer();
  const running = data?.running ?? null;
  if (disabled) return null;
  if (running) {
    return running.task === taskId ? (
      <StatusPill tone={STATUS_TONES.in_progress} size="sm">
        Timer läuft
      </StatusPill>
    ) : null;
  }
  return (
    <Button
      variant="ghost"
      size="xs"
      onClick={() =>
        startTimer.mutate(
          { task: taskId },
          {
            onSuccess: () => toast.success('Timer gestartet.'),
            onError: (error) => toast.error(error.message),
          },
        )
      }
      loading={startTimer.isPending}
    >
      <Play aria-hidden /> Timer starten
    </Button>
  );
}

function ChecklistSection({ taskId, canEdit }: { taskId: string; canEdit: boolean }) {
  const { data } = useChecklist(taskId);
  const { add, toggle, remove } = useChecklistMutations(taskId);
  const [newItem, setNewItem] = React.useState('');
  const items = data?.results ?? [];

  const submit = () => {
    const title = newItem.trim();
    if (!title) return;
    add.mutate(title, { onSuccess: () => setNewItem('') });
  };

  return (
    <div className="mt-5">
      <Label>
        Checkliste
        {items.length > 0 ? ` (${items.filter((i) => i.done).length}/${items.length})` : ''}
      </Label>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.id} className="group flex items-center gap-2">
            <input
              type="checkbox"
              checked={item.done}
              disabled={!canEdit}
              onChange={() => toggle.mutate(item)}
              className="size-3.5 accent-[var(--color-brand)]"
              aria-label={item.title}
            />
            <span
              className={cn(
                'flex-1 text-[length:var(--text-sm)]',
                item.done && 'text-[var(--color-ink-subtle)] line-through',
              )}
            >
              {item.title}
            </span>
            {canEdit ? (
              <button
                type="button"
                onClick={() => remove.mutate(item.id)}
                aria-label={`„${item.title}“ löschen`}
                className="invisible rounded p-0.5 text-[var(--color-ink-subtle)] group-hover:visible hover:text-[var(--color-danger)]"
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {canEdit ? (
        <div className="mt-2 flex gap-2">
          <Input
            value={newItem}
            placeholder="Neuer Punkt…"
            onChange={(event) => setNewItem(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submit();
            }}
          />
          <Button variant="secondary" size="icon-sm" onClick={submit} aria-label="Punkt hinzufügen">
            <Plus aria-hidden />
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function CommentsSection({ taskId, canEdit }: { taskId: string; canEdit: boolean }) {
  const { data } = useTaskComments(taskId);
  const addComment = useAddComment(taskId);
  const [content, setContent] = React.useState('');
  const comments = data?.results ?? [];

  const submit = () => {
    const trimmed = content.trim();
    if (!trimmed) return;
    addComment.mutate(trimmed, { onSuccess: () => setContent('') });
  };

  return (
    <div className="mt-5 border-t border-[var(--color-line)] pt-4">
      <Label>Kommentare ({comments.length})</Label>
      <ul className="space-y-3">
        {comments.map((comment) => (
          <li key={comment.id} className="flex gap-2">
            {comment.author ? <Avatar user={comment.author} size="sm" /> : null}
            <div className="min-w-0 flex-1">
              <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                {comment.author?.full_name ?? 'Unbekannt'} ·{' '}
                {new Date(comment.created_at).toLocaleString('de-DE', {
                  dateStyle: 'short',
                  timeStyle: 'short',
                })}
              </div>
              <p className="text-[length:var(--text-sm)] whitespace-pre-wrap">{comment.content}</p>
            </div>
          </li>
        ))}
      </ul>
      {canEdit ? (
        <div className="mt-3 space-y-2">
          <Textarea
            value={content}
            placeholder="Kommentar schreiben…"
            onChange={(event) => setContent(event.target.value)}
            className="min-h-[56px]"
          />
          <Button
            variant="primary"
            size="sm"
            onClick={submit}
            disabled={!content.trim()}
            loading={addComment.isPending}
          >
            Kommentieren
          </Button>
        </div>
      ) : null}
    </div>
  );
}
