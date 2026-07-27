'use client';

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Check, CornerDownRight, Loader2, Play, Plus, Trash2, UserPlus, X } from 'lucide-react';
import * as React from 'react';
import { createPortal } from 'react-dom';
import { toast } from 'sonner';

import { STATUS_TONES, StatusSelect } from '@/components/tasks/status-select';
import { Avatar } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { DeleteConfirmationDialog } from '@/components/ui/delete-confirmation-dialog';
import { Input, Label, Textarea } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { StatusPill } from '@/components/ui/status-pill';
import {
  PRIORITY_LABELS,
  useAddComment,
  useChecklist,
  useChecklistMutations,
  useCreateTask,
  useDeleteComment,
  useDeleteTask,
  useSprints,
  useTask,
  useTaskComments,
  useTasks,
  useUpdateTask,
  type Priority,
  type ChecklistItem,
  type Task,
  type TaskComment,
} from '@/lib/api/projects';
import { useStartTimer, useTimer } from '@/lib/api/time';
import { useMembers } from '@/lib/api/settings';
import { usePermissions, useSession } from '@/lib/session';
import { cn, formatHours } from '@/lib/utils';

/**
 * Right-hand task detail drawer (reference: the Plaky item card).
 *
 * The open task lives in the URL (?task=<id>) — handled by the page — so a
 * drawer state is linkable and survives reload.
 */
export function TaskDrawer({
  taskId,
  onClose,
  onOpenTask,
}: {
  taskId: string;
  onClose: () => void;
  onOpenTask?: (taskId: string) => void;
}) {
  const { data: task, isLoading } = useTask(taskId);
  const updateTask = useUpdateTask();
  const deleteTask = useDeleteTask();
  const permissions = usePermissions();
  const canEdit = permissions.can_write;
  const [deleteOpen, setDeleteOpen] = React.useState(false);

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
              {task.parent && task.parent_title && onOpenTask ? (
                <button
                  type="button"
                  onClick={() => onOpenTask(task.parent as string)}
                  className="mb-1 inline-flex items-center gap-1 text-[length:var(--text-2xs)] text-[var(--color-brand)] hover:underline"
                >
                  <CornerDownRight className="size-3 rotate-180" aria-hidden />
                  Übergeordnet: {task.parent_title}
                </button>
              ) : null}
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
                <Label htmlFor="drawer-start">Start am</Label>
                <Input
                  id="drawer-start"
                  type="date"
                  defaultValue={task.start_date ?? ''}
                  disabled={!canEdit}
                  onBlur={(event) => {
                    const value = event.target.value || null;
                    if (value !== task.start_date) patch({ start_date: value });
                  }}
                />
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
              <div className="col-span-2">
                <AssigneeField
                  selected={task.assignees}
                  selectedUsers={task.assignee_details}
                  disabled={!canEdit}
                  onChange={(assignees) => patch({ assignees })}
                />
              </div>
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

            <SubtasksSection task={task} canEdit={canEdit} onOpenTask={onOpenTask} />
            <ChecklistSection taskId={task.id} canEdit={canEdit} />
            <CommentsSection taskId={task.id} canEdit={canEdit} />
            {canEdit ? (
              <div className="mt-6 border-t border-[var(--color-line)] pt-4">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-[var(--color-danger)]"
                  onClick={() => setDeleteOpen(true)}
                >
                  <Trash2 aria-hidden /> Aufgabe löschen
                </Button>
              </div>
            ) : null}
          </div>
          <DeleteConfirmationDialog
            open={deleteOpen}
            onOpenChange={setDeleteOpen}
            title="Aufgabe löschen?"
            itemName={task.title}
            message="Unteraufgaben, Checklisten, Kommentare und angehängte Dateien werden ebenfalls gelöscht. Bereits erfasste Zeiten bleiben erhalten, verlieren aber die Aufgabenzuordnung."
            isPending={deleteTask.isPending}
            onConfirm={() =>
              deleteTask.mutate(task.id, {
                onSuccess: () => {
                  toast.success(`Aufgabe „${task.title}“ gelöscht.`);
                  onClose();
                },
                onError: (error) => toast.error(error.message),
              })
            }
          />
        </>
      )}
    </aside>
  );
}

/**
 * The task drawer as a floating, animated right-side overlay.
 *
 * The board embeds `TaskDrawer` inline as a persistent side panel; pages that
 * only occasionally need it (the project detail tabs) use this instead — it
 * slides in over the content with a click-to-close scrim, and stays mounted
 * through its exit animation so closing is animated too. Drive it by passing a
 * task id or null; render it once, unconditionally.
 */
export function TaskDrawerOverlay({
  taskId,
  onClose,
  onOpenTask,
}: {
  taskId: string | null;
  onClose: () => void;
  onOpenTask: (taskId: string) => void;
}) {
  // Keep the last id mounted while the exit animation plays out. Adopting a
  // newly opened task during render (guarded so it runs once and never loops)
  // is React's blessed props→state derivation — no synchronising effect.
  const [renderId, setRenderId] = React.useState<string | null>(taskId);
  if (taskId && taskId !== renderId) setRenderId(taskId);

  // taskId cleared but a panel is still on screen ⇒ animate it out.
  const closing = taskId === null && renderId !== null;

  // Lock body scroll while visible — the panel scrolls itself.
  React.useEffect(() => {
    if (renderId === null) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [renderId]);

  if (renderId === null || typeof document === 'undefined') return null;

  // Unmount only once the wrapper's OWN exit animation finishes — guarding on
  // currentTarget keeps bubbled child animations from tripping it early.
  const onAnimationEnd = (event: React.AnimationEvent<HTMLDivElement>) => {
    if (closing && event.target === event.currentTarget) setRenderId(null);
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Aufgabendetails schließen"
        onClick={onClose}
        className={cn(
          'absolute inset-0 cursor-default bg-black/30 backdrop-blur-[2px]',
          closing ? 'animate-overlay-out' : 'animate-overlay-in',
        )}
      />
      <div
        onAnimationEnd={onAnimationEnd}
        className={cn(
          'relative h-full w-[var(--spacing-drawer)] max-w-full',
          closing ? 'animate-drawer-out' : 'animate-drawer-in',
        )}
      >
        <TaskDrawer taskId={renderId} onClose={onClose} onOpenTask={onOpenTask} />
      </div>
    </div>,
    document.body,
  );
}

function AssigneeField({
  selected,
  selectedUsers,
  onChange,
  disabled,
}: {
  selected: string[];
  selectedUsers: Task['assignee_details'];
  onChange: (ids: string[]) => void;
  disabled: boolean;
}) {
  const { data: session } = useSession();
  const { data: memberships, isLoading } = useMembers(session?.workspace?.id);
  const members = (memberships ?? []).filter((membership) => membership.is_active);

  const content = (
    <div className="flex min-h-8 flex-wrap items-center gap-1.5">
      {selectedUsers.map((user) => (
        <span
          key={user.id}
          className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-panel-raised)] py-0.5 pr-2 pl-0.5 text-[length:var(--text-xs)]"
        >
          <Avatar user={user} size="sm" />
          {user.full_name || user.email}
        </span>
      ))}
      {selectedUsers.length === 0 ? (
        <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
          Nicht zugewiesen
        </span>
      ) : null}
      {!disabled ? <UserPlus className="ml-auto size-3.5 text-[var(--color-brand)]" /> : null}
    </div>
  );

  return (
    <div>
      <Label>Verantwortlich</Label>
      {disabled ? (
        content
      ) : (
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              type="button"
              className="w-full rounded-[var(--radius-sm)] border border-[var(--color-line)] bg-[var(--color-panel)] px-2 py-1 text-left transition-colors outline-none hover:border-[var(--color-brand)] focus-visible:ring-2 focus-visible:ring-[var(--color-brand)]"
              aria-label="Verantwortliche Personen auswählen"
            >
              {content}
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="start"
              sideOffset={4}
              className="z-50 max-h-72 min-w-64 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-panel-raised)] p-1 shadow-[var(--shadow-popover)]"
            >
              <DropdownMenu.Label className="px-2 py-1.5 text-[length:var(--text-2xs)] font-semibold tracking-wider text-[var(--color-ink-subtle)] uppercase">
                Teammitglieder
              </DropdownMenu.Label>
              {isLoading ? (
                <div className="px-2 py-2 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
                  Lädt…
                </div>
              ) : null}
              {members.map(({ user }) => {
                const checked = selected.includes(user.id);
                return (
                  <DropdownMenu.CheckboxItem
                    key={user.id}
                    checked={checked}
                    onSelect={(event) => event.preventDefault()}
                    onCheckedChange={() =>
                      onChange(
                        checked ? selected.filter((id) => id !== user.id) : [...selected, user.id],
                      )
                    }
                    className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-xs)] px-2 py-1.5 outline-none data-[highlighted]:bg-[var(--color-panel)]"
                  >
                    <Avatar user={user} size="sm" />
                    <span className="min-w-0 flex-1 truncate text-[length:var(--text-sm)]">
                      {user.full_name || user.email}
                    </span>
                    <DropdownMenu.ItemIndicator>
                      <Check className="size-3.5 text-[var(--color-brand)]" aria-hidden />
                    </DropdownMenu.ItemIndicator>
                  </DropdownMenu.CheckboxItem>
                );
              })}
              {!isLoading && members.length === 0 ? (
                <div className="px-2 py-2 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
                  Noch keine Teammitglieder vorhanden.
                </div>
              ) : null}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      )}
    </div>
  );
}

function SubtasksSection({
  task,
  canEdit,
  onOpenTask,
}: {
  task: Task;
  canEdit: boolean;
  onOpenTask?: (taskId: string) => void;
}) {
  const { data } = useTasks({ parent: task.id });
  const createTask = useCreateTask();
  const [title, setTitle] = React.useState('');
  const subtasks = data?.results ?? [];
  const done = subtasks.filter((item) => item.status === 'done').length;

  const submit = () => {
    const trimmed = title.trim();
    if (!trimmed) return;
    createTask.mutate(
      {
        title: trimmed,
        project: task.project,
        board: task.board,
        sprint: task.sprint,
        parent: task.id,
        priority: task.priority,
        billable: task.billable,
        status: 'todo',
      },
      {
        onSuccess: () => setTitle(''),
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <div className="mt-5 border-t border-[var(--color-line)] pt-4">
      <Label>Unteraufgaben{subtasks.length > 0 ? ` (${done}/${subtasks.length})` : ''}</Label>
      <ul className="space-y-1.5">
        {subtasks.map((subtask) => (
          <li
            key={subtask.id}
            className="flex items-center gap-2 rounded-[var(--radius-xs)] bg-[var(--color-panel-sunken)] px-2 py-1.5"
          >
            <StatusSelect taskId={subtask.id} status={subtask.status} disabled={!canEdit} compact />
            {onOpenTask ? (
              <button
                type="button"
                onClick={() => onOpenTask(subtask.id)}
                className="min-w-0 flex-1 truncate text-left text-[length:var(--text-sm)] hover:text-[var(--color-brand)]"
              >
                {subtask.title}
              </button>
            ) : (
              <span className="min-w-0 flex-1 truncate text-[length:var(--text-sm)]">
                {subtask.title}
              </span>
            )}
            {subtask.due_date ? (
              <span className="tabular text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                {new Date(subtask.due_date).toLocaleDateString('de-DE')}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {canEdit ? (
        <div className="mt-2 flex gap-2">
          <Input
            value={title}
            placeholder="Neue Unteraufgabe…"
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submit();
            }}
          />
          <Button
            variant="secondary"
            size="icon-sm"
            onClick={submit}
            loading={createTask.isPending}
            aria-label="Unteraufgabe hinzufügen"
          >
            <Plus aria-hidden />
          </Button>
        </div>
      ) : null}
    </div>
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
  const [itemToDelete, setItemToDelete] = React.useState<ChecklistItem | null>(null);
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
                onClick={() => setItemToDelete(item)}
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
      <DeleteConfirmationDialog
        open={Boolean(itemToDelete)}
        onOpenChange={(open) => !open && setItemToDelete(null)}
        title="Checklistenpunkt löschen?"
        itemName={itemToDelete?.title ?? ''}
        isPending={remove.isPending}
        onConfirm={() => {
          if (!itemToDelete) return;
          remove.mutate(itemToDelete.id, {
            onSuccess: () => setItemToDelete(null),
            onError: (error) => toast.error(error.message),
          });
        }}
      />
    </div>
  );
}

function CommentsSection({ taskId, canEdit }: { taskId: string; canEdit: boolean }) {
  const { data } = useTaskComments(taskId);
  const addComment = useAddComment(taskId);
  const deleteComment = useDeleteComment(taskId);
  const [content, setContent] = React.useState('');
  const [commentToDelete, setCommentToDelete] = React.useState<TaskComment | null>(null);
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
          <li key={comment.id} className="group flex gap-2">
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
            {canEdit ? (
              <button
                type="button"
                onClick={() => setCommentToDelete(comment)}
                aria-label="Kommentar löschen"
                className="invisible self-start rounded p-1 text-[var(--color-ink-subtle)] group-hover:visible hover:text-[var(--color-danger)]"
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            ) : null}
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
      <DeleteConfirmationDialog
        open={Boolean(commentToDelete)}
        onOpenChange={(open) => !open && setCommentToDelete(null)}
        title="Kommentar löschen?"
        itemName={commentToDelete?.content.slice(0, 80) ?? ''}
        isPending={deleteComment.isPending}
        onConfirm={() => {
          if (!commentToDelete) return;
          deleteComment.mutate(commentToDelete.id, {
            onSuccess: () => setCommentToDelete(null),
            onError: (error) => toast.error(error.message),
          });
        }}
      />
    </div>
  );
}
