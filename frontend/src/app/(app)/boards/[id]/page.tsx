'use client';

import { ArrowLeft, CalendarRange, Plus, Search, SquareKanban, Table2 } from 'lucide-react';
import Link from 'next/link';
import { useParams, usePathname, useRouter, useSearchParams } from 'next/navigation';
import * as React from 'react';

import { CreateTaskDialog } from '@/components/tasks/create-task-dialog';
import { KanbanBoard } from '@/components/tasks/kanban';
import { STATUS_TONES, StatusSelect } from '@/components/tasks/status-select';
import { TaskDrawer } from '@/components/tasks/task-drawer';
import { TaskTimeline } from '@/components/tasks/task-timeline';
import { AvatarStack } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { DetailErrorState } from '@/components/ui/detail-error';
import { ClickableRow, DataTable, GroupSection, Td, Th } from '@/components/ui/group-bar';
import { Input } from '@/components/ui/input';
import { PriorityPill } from '@/components/ui/status-pill';
import {
  PRIORITY_LABELS,
  TASK_STATUS_LABELS,
  TASK_STATUS_ORDER,
  useBoard,
  useTasks,
  type Task,
  type TaskListParams,
} from '@/lib/api/projects';
import { usePermissions } from '@/lib/session';
import { formatHours } from '@/lib/utils';

export default function BoardPage() {
  // useSearchParams requires a Suspense boundary during prerender in Next 16.
  return (
    <React.Suspense fallback={null}>
      <BoardPageInner />
    </React.Suspense>
  );
}

function BoardPageInner() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const permissions = usePermissions();

  const boardId = params.id;
  const { data: board, error: boardError } = useBoard(boardId);

  // Derived, not synced: the board's configured default applies until the user
  // explicitly switches — no effect, no cascading render.
  const [viewOverride, setViewOverride] = React.useState<'kanban' | 'table' | 'timeline' | null>(
    null,
  );
  const view = viewOverride ?? board?.default_view ?? 'kanban';
  const [search, setSearch] = React.useState('');
  const [createOpen, setCreateOpen] = React.useState(false);

  const listParams: TaskListParams = React.useMemo(() => ({ board: boardId }), [boardId]);
  const { data, isLoading } = useTasks(listParams);
  const allTasks = React.useMemo(
    () => (data?.results ?? []).filter((task) => task.parent === null),
    [data],
  );

  // Client-side quick filter — the whole board is already loaded.
  const tasks = React.useMemo(() => {
    if (!search.trim()) return allTasks;
    const needle = search.toLowerCase();
    return allTasks.filter((task) => task.title.toLowerCase().includes(needle));
  }, [allTasks, search]);

  // The open task lives in the URL: ?task=<id> — linkable and reload-safe.
  const openTaskId = searchParams.get('task');
  const setOpenTask = React.useCallback(
    (taskId: string | null) => {
      const next = new URLSearchParams(searchParams.toString());
      if (taskId) next.set('task', taskId);
      else next.delete('task');
      router.replace(`${pathname}${next.size ? `?${next}` : ''}`, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  if (boardError) {
    return (
      <DetailErrorState
        error={boardError}
        entityLabel="Board"
        backHref="/boards"
        backLabel="Alle Boards"
      />
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="px-5 pt-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-[length:var(--text-2xl)] font-semibold tracking-tight">
                {board ? board.project_name : '…'}
              </h1>
              <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
                {board ? `${board.client_name} · ${board.name}` : ''}
              </p>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/boards">
                <ArrowLeft aria-hidden /> Alle Boards
              </Link>
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-2 py-3">
            <div className="flex items-center gap-1 rounded-full bg-[var(--color-panel-sunken)] p-1">
              <ViewButton
                active={view === 'kanban'}
                onClick={() => setViewOverride('kanban')}
                icon={<SquareKanban className="size-3.5" aria-hidden />}
                label="Kanban"
              />
              <ViewButton
                active={view === 'table'}
                onClick={() => setViewOverride('table')}
                icon={<Table2 className="size-3.5" aria-hidden />}
                label="Tabelle"
              />
              <ViewButton
                active={view === 'timeline'}
                onClick={() => setViewOverride('timeline')}
                icon={<CalendarRange className="size-3.5" aria-hidden />}
                label="Zeitplan"
              />
            </div>
            <div className="relative w-full max-w-56">
              <Search
                className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-[var(--color-ink-subtle)]"
                aria-hidden
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Aufgaben filtern…"
                className="pl-8"
                aria-label="Aufgaben filtern"
              />
            </div>
            <span className="flex-1" />
            {permissions.can_write ? (
              <Button variant="primary" size="md" onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden /> Neue Aufgabe
              </Button>
            ) : null}
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-5">
          {isLoading ? (
            <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
          ) : view === 'kanban' ? (
            <KanbanBoard
              tasks={tasks}
              listParams={listParams}
              onOpenTask={(taskId) => setOpenTask(taskId)}
              canEdit={permissions.can_write}
            />
          ) : view === 'table' ? (
            <TaskTable tasks={tasks} onOpenTask={(taskId) => setOpenTask(taskId)} />
          ) : (
            <TaskTimeline tasks={tasks} onOpenTask={(taskId) => setOpenTask(taskId)} />
          )}
        </main>
      </div>

      {openTaskId ? (
        <TaskDrawer
          taskId={openTaskId}
          onClose={() => setOpenTask(null)}
          onOpenTask={setOpenTask}
        />
      ) : null}

      {board ? (
        <CreateTaskDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          boardId={board.id}
          projectId={board.project}
        />
      ) : null}
    </div>
  );
}

function ViewButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        active
          ? 'flex h-7 items-center gap-1.5 rounded-full bg-[var(--color-panel)] px-3 text-[length:var(--text-sm)] font-medium text-[var(--color-ink)] shadow-[var(--shadow-panel)]'
          : 'flex h-7 items-center gap-1.5 rounded-full px-3 text-[length:var(--text-sm)] text-[var(--color-ink-muted)] transition-colors hover:text-[var(--color-ink)]'
      }
    >
      {icon}
      {label}
    </button>
  );
}

function TaskTable({ tasks, onOpenTask }: { tasks: Task[]; onOpenTask: (id: string) => void }) {
  return (
    <>
      {TASK_STATUS_ORDER.map((status) => {
        const items = tasks
          .filter((task) => task.status === status)
          .sort((a, b) => Number(a.order) - Number(b.order));
        if (items.length === 0) return null;
        return (
          <GroupSection
            key={status}
            color={`var(--color-status-${STATUS_TONES[status]})`}
            title={TASK_STATUS_LABELS[status]}
            count={items.length}
          >
            <DataTable>
              <thead>
                <tr>
                  <Th className="w-[36%]">Aufgabe</Th>
                  <Th className="w-36">Status</Th>
                  <Th>Priorität</Th>
                  <Th>Verantwortlich</Th>
                  <Th>Fällig</Th>
                  <Th className="text-right">SP</Th>
                  <Th className="text-right">Erfasst</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((task) => (
                  <ClickableRow
                    key={task.id}
                    onClick={() => onOpenTask(task.id)}
                    tabIndex={0}
                    onKeyDown={(event) => event.key === 'Enter' && onOpenTask(task.id)}
                  >
                    <Td className="font-medium">{task.title}</Td>
                    <Td>
                      <StatusSelect taskId={task.id} status={task.status} />
                    </Td>
                    <Td>
                      <PriorityPill tone={task.priority}>
                        {PRIORITY_LABELS[task.priority]}
                      </PriorityPill>
                    </Td>
                    <Td>
                      <AvatarStack users={task.assignee_details} />
                    </Td>
                    <Td
                      className={
                        task.due_date &&
                        new Date(task.due_date) < new Date() &&
                        task.status !== 'done'
                          ? 'font-medium text-[var(--color-danger)]'
                          : 'text-[var(--color-ink-muted)]'
                      }
                    >
                      {task.due_date ? new Date(task.due_date).toLocaleDateString('de-DE') : '—'}
                    </Td>
                    <Td className="tabular text-right text-[var(--color-ink-muted)]">
                      {task.story_points ?? '—'}
                    </Td>
                    <Td className="tabular text-right text-[var(--color-ink-muted)]">
                      {task.logged_seconds > 0 ? formatHours(task.logged_seconds / 3600) : '—'}
                    </Td>
                  </ClickableRow>
                ))}
              </tbody>
            </DataTable>
          </GroupSection>
        );
      })}
    </>
  );
}
