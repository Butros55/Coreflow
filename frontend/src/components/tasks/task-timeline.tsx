'use client';

import { CalendarRange } from 'lucide-react';

import { STATUS_TONES } from '@/components/tasks/status-select';
import { EmptyState } from '@/components/ui/panel';
import { StatusPill } from '@/components/ui/status-pill';
import { TASK_STATUS_LABELS, type Task } from '@/lib/api/projects';

const DAY_MS = 24 * 60 * 60 * 1000;
const ROW_HEIGHT = 44;

function parseDay(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year ?? 0, (month ?? 1) - 1, day ?? 1);
}

function startOfDay(value: Date): Date {
  const copy = new Date(value);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function addDays(value: Date, days: number): Date {
  const copy = new Date(value);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function diffDays(from: Date, to: Date): number {
  // Date.UTC keeps calendar-day arithmetic stable across DST transitions.
  return Math.round(
    (Date.UTC(to.getFullYear(), to.getMonth(), to.getDate()) -
      Date.UTC(from.getFullYear(), from.getMonth(), from.getDate())) /
      DAY_MS,
  );
}

export interface TimelineTask {
  task: Task;
  start: Date;
  end: Date;
}

export interface TimelineModel {
  start: Date;
  end: Date;
  totalDays: number;
  pixelsPerDay: number;
  tickEvery: number;
  scheduled: TimelineTask[];
  undated: Task[];
}

export function buildTimelineModel(tasks: Task[]): TimelineModel | null {
  const scheduled: TimelineTask[] = [];
  const undated: Task[] = [];
  for (const task of tasks) {
    if (!task.start_date && !task.due_date) {
      undated.push(task);
      continue;
    }
    const first = parseDay(task.start_date ?? (task.due_date as string));
    const second = parseDay(task.due_date ?? (task.start_date as string));
    scheduled.push({
      task,
      start: first <= second ? first : second,
      end: first <= second ? second : first,
    });
  }
  if (scheduled.length === 0) return null;

  const earliest = new Date(Math.min(...scheduled.map((item) => item.start.getTime())));
  const latest = new Date(Math.max(...scheduled.map((item) => item.end.getTime())));
  const start = addDays(earliest, -1);
  const end = addDays(latest, 2);
  const totalDays = Math.max(diffDays(start, end), 1);
  const pixelsPerDay = totalDays <= 45 ? 28 : totalDays <= 180 ? 10 : 4;
  const tickEvery = totalDays <= 45 ? 1 : totalDays <= 180 ? 7 : 30;
  scheduled.sort((a, b) => a.start.getTime() - b.start.getTime());
  return { start, end, totalDays, pixelsPerDay, tickEvery, scheduled, undated };
}

export function TaskTimeline({
  tasks,
  onOpenTask,
}: {
  tasks: Task[];
  onOpenTask: (taskId: string) => void;
}) {
  const model = buildTimelineModel(tasks);
  if (!model) {
    return (
      <EmptyState
        icon={<CalendarRange className="size-8" aria-hidden />}
        title="Noch keine Zeitplanung"
        description="Trage in einer Aufgabe ein Start- oder Fälligkeitsdatum ein. Sie erscheint dann hier im Zeitplan."
      />
    );
  }

  const width = Math.max(720, model.totalDays * model.pixelsPerDay);
  const today = startOfDay(new Date());
  const todayOffset = diffDays(model.start, today) * model.pixelsPerDay;
  const showToday = today >= model.start && today <= model.end;
  const ticks = Array.from(
    { length: Math.ceil(model.totalDays / model.tickEvery) + 1 },
    (_, index) => addDays(model.start, index * model.tickEvery),
  ).filter((tick) => tick <= model.end);

  return (
    <div className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-panel)]">
      <div className="grid min-h-0 grid-cols-[240px_minmax(0,1fr)]">
        <div className="border-r border-[var(--color-line)]">
          <div className="flex h-10 items-center border-b border-[var(--color-line)] bg-[var(--color-panel-raised)] px-3 text-[length:var(--text-xs)] font-semibold text-[var(--color-ink-muted)]">
            Aufgabe
          </div>
          {model.scheduled.map(({ task }) => (
            <button
              key={task.id}
              type="button"
              onClick={() => onOpenTask(task.id)}
              className="flex w-full items-center gap-2 border-b border-[var(--color-line)] px-3 text-left hover:bg-[var(--color-panel-raised)]"
              style={{ height: ROW_HEIGHT }}
            >
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: `var(--color-status-${STATUS_TONES[task.status]})` }}
                aria-hidden
              />
              <span className="min-w-0">
                <span className="block truncate text-[length:var(--text-sm)] font-medium">
                  {task.title}
                </span>
                <span className="block truncate text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                  {task.assignee_details.map((user) => user.full_name).join(', ') ||
                    'Nicht zugewiesen'}
                </span>
              </span>
            </button>
          ))}
        </div>

        <div className="overflow-x-auto">
          <div className="relative" style={{ width }}>
            <div className="relative h-10 border-b border-[var(--color-line)] bg-[var(--color-panel-raised)]">
              {ticks.map((tick) => {
                const left = diffDays(model.start, tick) * model.pixelsPerDay;
                return (
                  <div
                    key={tick.toISOString()}
                    className="absolute inset-y-0 border-l border-[var(--color-line)] pl-1.5 text-[length:var(--text-2xs)] whitespace-nowrap text-[var(--color-ink-subtle)]"
                    style={{ left }}
                  >
                    <span className="relative top-3">
                      {tick.toLocaleDateString(
                        'de-DE',
                        model.tickEvery === 1
                          ? { weekday: 'short', day: '2-digit' }
                          : {
                              day: '2-digit',
                              month: 'short',
                              year: tick.getDate() <= 7 ? '2-digit' : undefined,
                            },
                      )}
                    </span>
                  </div>
                );
              })}
            </div>

            {model.scheduled.map(({ task, start, end }) => {
              const left = diffDays(model.start, start) * model.pixelsPerDay;
              const barWidth = Math.max((diffDays(start, end) + 1) * model.pixelsPerDay, 8);
              return (
                <div
                  key={task.id}
                  className="relative border-b border-[var(--color-line)]"
                  style={{ height: ROW_HEIGHT }}
                >
                  {ticks.map((tick) => (
                    <span
                      key={tick.toISOString()}
                      className="absolute inset-y-0 border-l border-[var(--color-line)] opacity-60"
                      style={{ left: diffDays(model.start, tick) * model.pixelsPerDay }}
                      aria-hidden
                    />
                  ))}
                  <button
                    type="button"
                    onClick={() => onOpenTask(task.id)}
                    className="absolute top-2 flex h-7 items-center overflow-hidden rounded-[var(--radius-xs)] px-2 text-left text-[length:var(--text-2xs)] font-semibold whitespace-nowrap text-[var(--color-canvas)] shadow-sm transition-[filter] hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-brand)]"
                    style={{
                      left,
                      width: barWidth,
                      backgroundColor: `var(--color-status-${STATUS_TONES[task.status]})`,
                    }}
                    aria-label={`${task.title}: ${start.toLocaleDateString('de-DE')} bis ${end.toLocaleDateString('de-DE')}, ${TASK_STATUS_LABELS[task.status]}`}
                    title={`${task.title} · ${start.toLocaleDateString('de-DE')} – ${end.toLocaleDateString('de-DE')}`}
                  >
                    {barWidth >= 90 ? task.title : ''}
                  </button>
                </div>
              );
            })}

            {showToday ? (
              <div
                className="pointer-events-none absolute top-0 bottom-0 z-10 w-px bg-[var(--color-danger)]"
                style={{ left: todayOffset }}
                aria-hidden
              >
                <span className="absolute top-0 -translate-x-1/2 rounded-b bg-[var(--color-danger)] px-1 text-[9px] font-semibold text-white">
                  Heute
                </span>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {model.undated.length > 0 ? (
        <div className="border-t border-[var(--color-line)] bg-[var(--color-panel-sunken)] px-3 py-2">
          <div className="mb-1.5 text-[length:var(--text-2xs)] font-medium text-[var(--color-ink-subtle)]">
            Ohne Datum ({model.undated.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {model.undated.map((task) => (
              <button key={task.id} type="button" onClick={() => onOpenTask(task.id)}>
                <StatusPill tone={STATUS_TONES[task.status]} size="sm">
                  {task.title}
                </StatusPill>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
