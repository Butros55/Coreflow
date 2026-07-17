'use client';

import { ListChecks } from 'lucide-react';
import { useRouter } from 'next/navigation';
import * as React from 'react';

import { PageHeader } from '@/components/layout/app-shell';
import { StatusSelect } from '@/components/tasks/status-select';
import { ClickableRow, DataTable, GroupSection, Td, Th } from '@/components/ui/group-bar';
import { EmptyState } from '@/components/ui/panel';
import { PriorityPill } from '@/components/ui/status-pill';
import { PRIORITY_LABELS, useTasks, type Task } from '@/lib/api/projects';
import { formatHours } from '@/lib/utils';

type Bucket = 'overdue' | 'today' | 'week' | 'later' | 'no_date';

const BUCKETS: { key: Bucket; title: string; color: string }[] = [
  { key: 'overdue', title: 'Überfällig', color: 'var(--color-status-stuck)' },
  { key: 'today', title: 'Heute', color: 'var(--color-status-progress)' },
  { key: 'week', title: 'Diese Woche', color: 'var(--color-status-todo)' },
  { key: 'later', title: 'Später', color: 'var(--color-status-done)' },
  { key: 'no_date', title: 'Ohne Datum', color: 'var(--color-status-hold)' },
];

function bucketOf(task: Task): Bucket {
  if (!task.due_date) return 'no_date';
  const due = new Date(task.due_date);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const endOfWeek = new Date(today);
  endOfWeek.setDate(endOfWeek.getDate() + (7 - ((today.getDay() + 6) % 7)));
  if (due < today) return 'overdue';
  if (due.getTime() === today.getTime()) return 'today';
  if (due < endOfWeek) return 'week';
  return 'later';
}

export default function MyTasksPage() {
  const router = useRouter();
  const { data, isLoading } = useTasks({ assigned_to_me: true });
  const tasks = React.useMemo(
    () => (data?.results ?? []).filter((task) => task.status !== 'done'),
    [data],
  );

  const grouped = BUCKETS.map((bucket) => ({
    ...bucket,
    tasks: tasks
      .filter((task) => bucketOf(task) === bucket.key)
      .sort((a, b) => (a.due_date ?? '9999').localeCompare(b.due_date ?? '9999')),
  })).filter((bucket) => bucket.tasks.length > 0);

  const openTask = (task: Task) => router.push(`/boards/${task.board}?task=${task.id}`);

  return (
    <>
      <PageHeader title="Meine Aufgaben" description={`${tasks.length} offene Aufgaben`} />
      <div className="p-5">
        {isLoading ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : grouped.length === 0 ? (
          <EmptyState
            icon={<ListChecks className="size-8" aria-hidden />}
            title="Alles erledigt"
            description="Dir ist aktuell keine offene Aufgabe zugewiesen."
          />
        ) : (
          grouped.map((bucket) => (
            <GroupSection
              key={bucket.key}
              color={bucket.color}
              title={bucket.title}
              count={bucket.tasks.length}
            >
              <DataTable>
                <thead>
                  <tr>
                    <Th className="w-[34%]">Aufgabe</Th>
                    <Th>Projekt</Th>
                    <Th className="w-36">Status</Th>
                    <Th>Priorität</Th>
                    <Th>Fällig</Th>
                    <Th className="text-right">Erfasst</Th>
                  </tr>
                </thead>
                <tbody>
                  {bucket.tasks.map((task) => (
                    <ClickableRow
                      key={task.id}
                      onClick={() => openTask(task)}
                      tabIndex={0}
                      onKeyDown={(event) => event.key === 'Enter' && openTask(task)}
                    >
                      <Td className="font-medium">{task.title}</Td>
                      <Td>
                        <div className="text-[var(--color-ink-muted)]">{task.project_name}</div>
                        <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                          {task.client_name}
                        </div>
                      </Td>
                      <Td>
                        <StatusSelect taskId={task.id} status={task.status} />
                      </Td>
                      <Td>
                        <PriorityPill tone={task.priority}>
                          {PRIORITY_LABELS[task.priority]}
                        </PriorityPill>
                      </Td>
                      <Td
                        className={
                          bucket.key === 'overdue'
                            ? 'font-medium text-[var(--color-danger)]'
                            : 'text-[var(--color-ink-muted)]'
                        }
                      >
                        {task.due_date ? new Date(task.due_date).toLocaleDateString('de-DE') : '—'}
                      </Td>
                      <Td className="tabular text-right text-[var(--color-ink-muted)]">
                        {task.logged_seconds > 0 ? formatHours(task.logged_seconds / 3600) : '—'}
                      </Td>
                    </ClickableRow>
                  ))}
                </tbody>
              </DataTable>
            </GroupSection>
          ))
        )}
      </div>
    </>
  );
}
