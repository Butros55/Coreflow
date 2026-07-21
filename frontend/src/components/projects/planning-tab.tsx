'use client';

import {
  CalendarClock,
  CalendarRange,
  Check,
  ListTodo,
  Pencil,
  Play,
  Plus,
  Trash2,
} from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PhaseFormDialog } from '@/components/projects/phase-dialog';
import { SprintFormDialog } from '@/components/projects/sprint-dialog';
import { StatusSelect } from '@/components/tasks/status-select';
import { Button } from '@/components/ui/button';
import { DeleteConfirmationDialog } from '@/components/ui/delete-confirmation-dialog';
import { DataTable, Td, Th } from '@/components/ui/group-bar';
import { EmptyState, Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import {
  PHASE_STATUS_LABELS,
  SPRINT_STATUS_LABELS,
  useDeletePhase,
  useDeleteSprint,
  useUpdateSprint,
  type Project,
  type ProjectPhase,
  type Sprint,
  type Task,
} from '@/lib/api/projects';
import { formatHours } from '@/lib/utils';

const DAY_MS = 86_400_000;

function dateLabel(value: string | null): string {
  return value ? new Date(value).toLocaleDateString('de-DE') : '—';
}

/** Whole days from today (midnight-safe); negative = in the past. */
function daysFromToday(value: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(value);
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / DAY_MS);
}

const SPRINT_TONES = { planned: 'hold', active: 'progress', completed: 'done' } as const;
const PHASE_TONES = { planned: 'hold', active: 'progress', completed: 'done' } as const;

/**
 * Planning surface of the project detail page: sprints with their tasks and
 * quick actions, the backlog, upcoming due dates, and phase management —
 * everything needed to see what has to be done by when.
 */
export function ProjectPlanningTab({
  project,
  sprints,
  tasks,
  canEdit,
  onOpenTask,
  onCreateTask,
}: {
  project: Project;
  sprints: Sprint[];
  tasks: Task[];
  canEdit: boolean;
  onOpenTask: (taskId: string) => void;
  onCreateTask: (defaults: { sprint?: string | null; phase?: string | null }) => void;
}) {
  const updateSprint = useUpdateSprint();
  const deleteSprint = useDeleteSprint();
  const deletePhase = useDeletePhase();

  const [sprintDialogOpen, setSprintDialogOpen] = React.useState(false);
  const [sprintToEdit, setSprintToEdit] = React.useState<Sprint | undefined>(undefined);
  const [sprintToDelete, setSprintToDelete] = React.useState<Sprint | null>(null);
  const [phaseDialogOpen, setPhaseDialogOpen] = React.useState(false);
  const [phaseToEdit, setPhaseToEdit] = React.useState<ProjectPhase | undefined>(undefined);
  const [phaseToDelete, setPhaseToDelete] = React.useState<ProjectPhase | null>(null);

  const topLevelTasks = React.useMemo(() => tasks.filter((task) => !task.archived), [tasks]);

  const sortedSprints = React.useMemo(() => {
    const rank = { active: 0, planned: 1, completed: 2 } as const;
    return [...sprints].sort((a, b) => {
      if (rank[a.status] !== rank[b.status]) return rank[a.status] - rank[b.status];
      const aDate = a.start_date ?? '9999-12-31';
      const bDate = b.start_date ?? '9999-12-31';
      return a.status === 'completed' ? bDate.localeCompare(aDate) : aDate.localeCompare(bDate);
    });
  }, [sprints]);

  const backlogTasks = React.useMemo(
    () =>
      topLevelTasks
        .filter((task) => task.sprint === null && task.status !== 'done')
        .sort(byDueDate),
    [topLevelTasks],
  );

  const openSprintDialog = (sprint?: Sprint) => {
    setSprintToEdit(sprint);
    setSprintDialogOpen(true);
  };
  const openPhaseDialog = (phase?: ProjectPhase) => {
    setPhaseToEdit(phase);
    setPhaseDialogOpen(true);
  };

  const setSprintStatus = (sprint: Sprint, status: Sprint['status'], message: string) =>
    updateSprint.mutate(
      { id: sprint.id, status },
      {
        onSuccess: () => toast.success(message),
        onError: (error) => toast.error(error.message),
      },
    );

  return (
    <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
      <div className="space-y-4">
        <Panel>
          <PanelHeader>
            <PanelTitle>Sprints</PanelTitle>
            {canEdit ? (
              <Button variant="secondary" size="xs" onClick={() => openSprintDialog(undefined)}>
                <Plus aria-hidden /> Neuer Sprint
              </Button>
            ) : null}
          </PanelHeader>
          <PanelBody className="space-y-3">
            {sortedSprints.length === 0 ? (
              <EmptyState
                icon={<CalendarClock className="size-7" aria-hidden />}
                title="Noch keine Sprints"
                description="Sprints bündeln Aufgaben in feste Zeiträume — so ist klar, was bis wann erledigt sein muss."
                action={
                  canEdit ? (
                    <Button variant="primary" size="sm" onClick={() => openSprintDialog(undefined)}>
                      <Plus aria-hidden /> Ersten Sprint anlegen
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              sortedSprints.map((sprint) => (
                <SprintCard
                  key={sprint.id}
                  sprint={sprint}
                  tasks={topLevelTasks.filter((task) => task.sprint === sprint.id)}
                  canEdit={canEdit}
                  onOpenTask={onOpenTask}
                  onAddTask={() => onCreateTask({ sprint: sprint.id })}
                  onEdit={() => openSprintDialog(sprint)}
                  onDelete={() => setSprintToDelete(sprint)}
                  onStart={() => setSprintStatus(sprint, 'active', `„${sprint.name}“ gestartet.`)}
                  onComplete={() =>
                    setSprintStatus(sprint, 'completed', `„${sprint.name}“ abgeschlossen.`)
                  }
                />
              ))
            )}
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Backlog</PanelTitle>
            <div className="flex items-center gap-2">
              <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
                {backlogTasks.length} offen
              </span>
              {canEdit ? (
                <Button
                  variant="secondary"
                  size="xs"
                  onClick={() => onCreateTask({ sprint: null })}
                >
                  <Plus aria-hidden /> Aufgabe
                </Button>
              ) : null}
            </div>
          </PanelHeader>
          {backlogTasks.length === 0 ? (
            <PanelBody>
              <EmptyState
                icon={<ListTodo className="size-7" aria-hidden />}
                title="Backlog ist leer"
                description="Alle offenen Aufgaben sind einem Sprint zugeordnet."
              />
            </PanelBody>
          ) : (
            <PanelBody className="space-y-1">
              {backlogTasks.map((task) => (
                <TaskRow key={task.id} task={task} canEdit={canEdit} onOpenTask={onOpenTask} />
              ))}
            </PanelBody>
          )}
        </Panel>
      </div>

      <div className="space-y-4">
        <DueOverviewPanel tasks={topLevelTasks} onOpenTask={onOpenTask} />

        <Panel>
          <PanelHeader>
            <PanelTitle>Phasen</PanelTitle>
            {canEdit ? (
              <Button variant="secondary" size="xs" onClick={() => openPhaseDialog(undefined)}>
                <Plus aria-hidden /> Neue Phase
              </Button>
            ) : null}
          </PanelHeader>
          {project.phases.length === 0 ? (
            <PanelBody>
              <EmptyState
                icon={<CalendarRange className="size-7" aria-hidden />}
                title="Noch keine Phasen"
                description="Phasen gliedern das Projekt in Abschnitte mit eigenem Zeitraum."
              />
            </PanelBody>
          ) : (
            <DataTable>
              <thead>
                <tr>
                  <Th>Phase</Th>
                  <Th>Status</Th>
                  <Th>Zeitraum</Th>
                  <Th className="text-right">Aufgaben</Th>
                  {canEdit ? <Th className="w-16" aria-label="Aktionen" /> : null}
                </tr>
              </thead>
              <tbody>
                {[...project.phases]
                  .sort((a, b) => a.order - b.order)
                  .map((phase) => {
                    const phaseTasks = topLevelTasks.filter((task) => task.phase === phase.id);
                    const done = phaseTasks.filter((task) => task.status === 'done').length;
                    return (
                      <tr key={phase.id} className="last:[&>td]:border-b-0">
                        <Td>
                          <div className="font-medium">{phase.name}</div>
                          {phase.planned_hours ? (
                            <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                              {formatHours(phase.planned_hours)} geplant
                            </div>
                          ) : null}
                        </Td>
                        <Td>
                          <StatusTint tone={PHASE_TONES[phase.status]}>
                            {PHASE_STATUS_LABELS[phase.status]}
                          </StatusTint>
                        </Td>
                        <Td className="text-[var(--color-ink-muted)]">
                          {dateLabel(phase.start_date)} – {dateLabel(phase.end_date)}
                        </Td>
                        <Td className="tabular text-right text-[var(--color-ink-muted)]">
                          {phaseTasks.length > 0 ? `${done}/${phaseTasks.length}` : '—'}
                        </Td>
                        {canEdit ? (
                          <Td className="text-right">
                            <div className="flex justify-end gap-1">
                              <IconButton
                                label={`Phase „${phase.name}“ bearbeiten`}
                                onClick={() => openPhaseDialog(phase)}
                              >
                                <Pencil className="size-3.5" aria-hidden />
                              </IconButton>
                              <IconButton
                                label={`Phase „${phase.name}“ löschen`}
                                danger
                                onClick={() => setPhaseToDelete(phase)}
                              >
                                <Trash2 className="size-3.5" aria-hidden />
                              </IconButton>
                            </div>
                          </Td>
                        ) : null}
                      </tr>
                    );
                  })}
              </tbody>
            </DataTable>
          )}
        </Panel>
      </div>

      <SprintFormDialog
        open={sprintDialogOpen}
        onOpenChange={(open) => {
          setSprintDialogOpen(open);
          if (!open) setSprintToEdit(undefined);
        }}
        projectId={project.id}
        boardId={project.default_board}
        sprint={sprintToEdit}
      />
      <PhaseFormDialog
        open={phaseDialogOpen}
        onOpenChange={(open) => {
          setPhaseDialogOpen(open);
          if (!open) setPhaseToEdit(undefined);
        }}
        projectId={project.id}
        nextOrder={
          project.phases.length > 0
            ? Math.max(...project.phases.map((phase) => phase.order)) + 1
            : 0
        }
        phase={phaseToEdit}
      />
      <DeleteConfirmationDialog
        open={Boolean(sprintToDelete)}
        onOpenChange={(open) => !open && setSprintToDelete(null)}
        title="Sprint löschen?"
        itemName={sprintToDelete?.name ?? ''}
        message="Zugeordnete Aufgaben bleiben erhalten und wandern zurück in den Backlog."
        isPending={deleteSprint.isPending}
        onConfirm={() => {
          if (!sprintToDelete) return;
          deleteSprint.mutate(sprintToDelete.id, {
            onSuccess: () => {
              toast.success(`Sprint „${sprintToDelete.name}“ gelöscht.`);
              setSprintToDelete(null);
            },
            onError: (error) => toast.error(error.message),
          });
        }}
      />
      <DeleteConfirmationDialog
        open={Boolean(phaseToDelete)}
        onOpenChange={(open) => !open && setPhaseToDelete(null)}
        title="Phase löschen?"
        itemName={phaseToDelete?.name ?? ''}
        message="Zugeordnete Aufgaben bleiben erhalten und verlieren nur die Phasenzuordnung."
        isPending={deletePhase.isPending}
        onConfirm={() => {
          if (!phaseToDelete) return;
          deletePhase.mutate(phaseToDelete.id, {
            onSuccess: () => {
              toast.success(`Phase „${phaseToDelete.name}“ gelöscht.`);
              setPhaseToDelete(null);
            },
            onError: (error) => toast.error(error.message),
          });
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sprint card
// ---------------------------------------------------------------------------

function SprintCard({
  sprint,
  tasks,
  canEdit,
  onOpenTask,
  onAddTask,
  onEdit,
  onDelete,
  onStart,
  onComplete,
}: {
  sprint: Sprint;
  tasks: Task[];
  canEdit: boolean;
  onOpenTask: (taskId: string) => void;
  onAddTask: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onStart: () => void;
  onComplete: () => void;
}) {
  const done = tasks.filter((task) => task.status === 'done').length;
  const total = tasks.length;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;
  const openTasks = tasks.filter((task) => task.status !== 'done').sort(byDueDate);
  const estimated = tasks.reduce(
    (sum, task) => sum + (task.estimated_hours ? Number(task.estimated_hours) : 0),
    0,
  );

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-panel-sunken)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{sprint.name}</span>
            <StatusTint tone={SPRINT_TONES[sprint.status]}>
              {SPRINT_STATUS_LABELS[sprint.status]}
            </StatusTint>
            <SprintCountdown sprint={sprint} />
          </div>
          {sprint.goal ? (
            <p className="mt-0.5 text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
              {sprint.goal}
            </p>
          ) : null}
          <p className="mt-0.5 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            {dateLabel(sprint.start_date)} – {dateLabel(sprint.end_date)}
            {estimated > 0
              ? ` · ${formatHours(estimated)} geschätzt${
                  sprint.capacity_hours ? ` von ${formatHours(sprint.capacity_hours)}` : ''
                }`
              : sprint.capacity_hours
                ? ` · Kapazität ${formatHours(sprint.capacity_hours)}`
                : ''}
          </p>
        </div>
        {canEdit ? (
          <div className="flex items-center gap-1">
            {sprint.status === 'planned' ? (
              <Button variant="secondary" size="xs" onClick={onStart}>
                <Play aria-hidden /> Starten
              </Button>
            ) : null}
            {sprint.status === 'active' ? (
              <Button variant="secondary" size="xs" onClick={onComplete}>
                <Check aria-hidden /> Abschließen
              </Button>
            ) : null}
            <IconButton label={`Sprint „${sprint.name}“ bearbeiten`} onClick={onEdit}>
              <Pencil className="size-3.5" aria-hidden />
            </IconButton>
            <IconButton label={`Sprint „${sprint.name}“ löschen`} danger onClick={onDelete}>
              <Trash2 className="size-3.5" aria-hidden />
            </IconButton>
          </div>
        ) : null}
      </div>

      {total > 0 ? (
        <div className="mt-2">
          <div className="mb-1 flex items-baseline justify-between text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            <span>
              {done}/{total} Aufgaben erledigt
            </span>
            <span>{percent} %</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-panel)]">
            <div
              className="h-full rounded-full bg-[var(--color-brand)]"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      ) : null}

      {openTasks.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {openTasks.map((task) => (
            <TaskRow key={task.id} task={task} canEdit={canEdit} onOpenTask={onOpenTask} />
          ))}
        </ul>
      ) : total > 0 ? (
        <p className="mt-2 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
          Alle Aufgaben dieses Sprints sind erledigt.
        </p>
      ) : (
        <p className="mt-2 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
          Noch keine Aufgaben zugeordnet.
        </p>
      )}

      {canEdit && sprint.status !== 'completed' ? (
        <Button variant="ghost" size="xs" className="mt-2" onClick={onAddTask}>
          <Plus aria-hidden /> Aufgabe hinzufügen
        </Button>
      ) : null}
    </div>
  );
}

function SprintCountdown({ sprint }: { sprint: Sprint }) {
  if (sprint.status === 'active' && sprint.end_date) {
    const days = daysFromToday(sprint.end_date);
    if (days < 0) {
      return (
        <span className="text-[length:var(--text-2xs)] font-medium text-[var(--color-danger)]">
          {Math.abs(days)} {Math.abs(days) === 1 ? 'Tag' : 'Tage'} überzogen
        </span>
      );
    }
    return (
      <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
        {days === 0 ? 'endet heute' : `noch ${days} ${days === 1 ? 'Tag' : 'Tage'}`}
      </span>
    );
  }
  if (sprint.status === 'planned' && sprint.start_date) {
    const days = daysFromToday(sprint.start_date);
    if (days > 0) {
      return (
        <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
          startet in {days} {days === 1 ? 'Tag' : 'Tagen'}
        </span>
      );
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Task row + due overview
// ---------------------------------------------------------------------------

function byDueDate(a: Task, b: Task): number {
  return (a.due_date ?? '9999-12-31').localeCompare(b.due_date ?? '9999-12-31');
}

function TaskRow({
  task,
  canEdit,
  onOpenTask,
}: {
  task: Task;
  canEdit: boolean;
  onOpenTask: (taskId: string) => void;
}) {
  const overdue = task.due_date !== null && daysFromToday(task.due_date) < 0;
  return (
    <li className="flex items-center gap-2 rounded-[var(--radius-xs)] bg-[var(--color-panel)] px-2 py-1.5">
      <StatusSelect taskId={task.id} status={task.status} disabled={!canEdit} compact />
      <button
        type="button"
        onClick={() => onOpenTask(task.id)}
        className="min-w-0 flex-1 truncate text-left text-[length:var(--text-sm)] hover:text-[var(--color-brand)]"
      >
        {task.title}
      </button>
      {task.due_date ? (
        <span
          className={
            overdue
              ? 'tabular text-[length:var(--text-2xs)] font-medium text-[var(--color-danger)]'
              : 'tabular text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]'
          }
        >
          {dateLabel(task.due_date)}
        </span>
      ) : null}
    </li>
  );
}

function DueOverviewPanel({
  tasks,
  onOpenTask,
}: {
  tasks: Task[];
  onOpenTask: (taskId: string) => void;
}) {
  const open = tasks.filter((task) => task.status !== 'done');
  const withDue = open.filter((task) => task.due_date !== null).sort(byDueDate);
  const overdue = withDue.filter((task) => daysFromToday(task.due_date as string) < 0);
  const today = withDue.filter((task) => daysFromToday(task.due_date as string) === 0);
  const week = withDue.filter((task) => {
    const days = daysFromToday(task.due_date as string);
    return days > 0 && days <= 7;
  });
  const later = withDue.filter((task) => daysFromToday(task.due_date as string) > 7);
  const noDue = open.length - withDue.length;

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Fälligkeiten</PanelTitle>
        <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
          {open.length} offene Aufgaben
        </span>
      </PanelHeader>
      <PanelBody className="space-y-3">
        {withDue.length === 0 ? (
          <EmptyState
            icon={<CalendarClock className="size-7" aria-hidden />}
            title="Keine Termine gesetzt"
            description="Vergib Fälligkeiten, um zu sehen, was bis wann erledigt sein muss."
          />
        ) : (
          <>
            <DueGroup
              title="Überfällig"
              tasks={overdue}
              tone="var(--color-danger)"
              onOpenTask={onOpenTask}
            />
            <DueGroup
              title="Heute"
              tasks={today}
              tone="var(--color-status-progress)"
              onOpenTask={onOpenTask}
            />
            <DueGroup
              title="Nächste 7 Tage"
              tasks={week}
              tone="var(--color-status-todo)"
              onOpenTask={onOpenTask}
            />
            <DueGroup
              title="Später"
              tasks={later}
              tone="var(--color-ink-subtle)"
              onOpenTask={onOpenTask}
            />
          </>
        )}
        {noDue > 0 ? (
          <p className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            {noDue} offene {noDue === 1 ? 'Aufgabe' : 'Aufgaben'} ohne Fälligkeitsdatum.
          </p>
        ) : null}
      </PanelBody>
    </Panel>
  );
}

function DueGroup({
  title,
  tasks,
  tone,
  onOpenTask,
}: {
  title: string;
  tasks: Task[];
  tone: string;
  onOpenTask: (taskId: string) => void;
}) {
  if (tasks.length === 0) return null;
  return (
    <div>
      <div className="mb-1 flex items-center gap-1.5 text-[length:var(--text-2xs)] font-semibold tracking-wider uppercase">
        <span className="inline-block size-1.5 rounded-full" style={{ backgroundColor: tone }} />
        <span style={{ color: tone }}>
          {title} ({tasks.length})
        </span>
      </div>
      <ul className="space-y-1">
        {tasks.map((task) => (
          <li key={task.id} className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onOpenTask(task.id)}
              className="min-w-0 flex-1 truncate text-left text-[length:var(--text-sm)] hover:text-[var(--color-brand)]"
            >
              {task.title}
            </button>
            <span className="tabular text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
              {task.sprint_name ? `${task.sprint_name} · ` : ''}
              {dateLabel(task.due_date)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  danger = false,
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={
        danger
          ? 'rounded p-1 text-[var(--color-ink-subtle)] transition-colors hover:bg-[var(--color-danger)]/10 hover:text-[var(--color-danger)]'
          : 'rounded p-1 text-[var(--color-ink-subtle)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)]'
      }
    >
      {children}
    </button>
  );
}
