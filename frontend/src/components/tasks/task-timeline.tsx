'use client';

import { CalendarRange } from 'lucide-react';
import * as React from 'react';

import { STATUS_TONES } from '@/components/tasks/status-select';
import { EmptyState } from '@/components/ui/panel';
import { StatusPill } from '@/components/ui/status-pill';
import { TASK_STATUS_LABELS, type Task } from '@/lib/api/projects';
import { cn } from '@/lib/utils';

const DAY_MS = 24 * 60 * 60 * 1000;
const ROW_HEIGHT = 44;
const HEADER_HEIGHT = 48;
/** The chart should fill a typical panel even for short ranges. */
const MIN_CHART_WIDTH = 880;

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

function isWeekend(value: Date): boolean {
  const day = value.getDay();
  return day === 0 || day === 6;
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
  // Day columns are wide enough for a readable label; short ranges scale up so
  // the chart fills the panel instead of huddling in a corner.
  const pixelsPerDay =
    totalDays <= 45
      ? Math.min(64, Math.max(44, Math.ceil(MIN_CHART_WIDTH / totalDays)))
      : totalDays <= 180
        ? 12
        : 5;
  const tickEvery = totalDays <= 45 ? 1 : totalDays <= 180 ? 7 : 30;
  scheduled.sort((a, b) => a.start.getTime() - b.start.getTime());
  return { start, end, totalDays, pixelsPerDay, tickEvery, scheduled, undated };
}

/** Consecutive-month segments for the upper header row. */
function monthSegments(model: TimelineModel): { label: string; left: number; width: number }[] {
  const segments: { label: string; left: number; width: number }[] = [];
  for (let index = 0; index < model.totalDays; index += 1) {
    const day = addDays(model.start, index);
    const label = day.toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });
    const previous = segments[segments.length - 1];
    if (previous && previous.label === label) {
      previous.width += model.pixelsPerDay;
    } else {
      segments.push({ label, left: index * model.pixelsPerDay, width: model.pixelsPerDay });
    }
  }
  return segments;
}

export function TaskTimeline({
  tasks,
  onOpenTask,
}: {
  tasks: Task[];
  onOpenTask: (taskId: string) => void;
}) {
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const model = buildTimelineModel(tasks);

  const today = startOfDay(new Date());
  const todayOffset = model ? diffDays(model.start, today) * model.pixelsPerDay : 0;
  const showToday = model ? today >= model.start && today <= model.end : false;

  // Center "today" on first paint — the interesting part of a plan is now,
  // not its earliest date.
  React.useEffect(() => {
    const node = scrollRef.current;
    if (!node || !showToday) return;
    const overflow = node.scrollWidth - node.clientWidth;
    if (overflow <= 8) return;
    node.scrollLeft = Math.min(Math.max(0, todayOffset - node.clientWidth / 2), overflow);
  }, [showToday, todayOffset]);

  if (!model) {
    return (
      <EmptyState
        icon={<CalendarRange className="size-8" aria-hidden />}
        title="Noch keine Zeitplanung"
        description="Trage in einer Aufgabe ein Start- oder Fälligkeitsdatum ein. Sie erscheint dann hier im Zeitplan."
      />
    );
  }

  const width = model.totalDays * model.pixelsPerDay;
  const bodyHeight = model.scheduled.length * ROW_HEIGHT;
  const daily = model.tickEvery === 1;
  const days = Array.from({ length: model.totalDays }, (_, index) => addDays(model.start, index));
  const ticks = daily
    ? days
    : Array.from({ length: Math.ceil(model.totalDays / model.tickEvery) + 1 }, (_, index) =>
        addDays(model.start, index * model.tickEvery),
      ).filter((tick) => tick <= model.end);

  return (
    <div className="overflow-hidden rounded-[var(--radius-xl)] border border-[var(--color-line-subtle)] bg-[var(--color-panel)] shadow-[var(--shadow-panel)]">
      <div className="grid min-h-0 grid-cols-[240px_minmax(0,1fr)]">
        {/* Task label column */}
        <div className="border-r border-[var(--color-line)]">
          <div
            className="flex items-center border-b border-[var(--color-line)] px-3 text-[length:var(--text-xs)] font-semibold text-[var(--color-ink-muted)]"
            style={{ height: HEADER_HEIGHT }}
          >
            Aufgabe
          </div>
          {model.scheduled.map(({ task }) => (
            <button
              key={task.id}
              type="button"
              onClick={() => onOpenTask(task.id)}
              className="flex w-full items-center gap-2.5 border-b border-[var(--color-line-subtle)] px-3 text-left transition-colors last:border-b-0 hover:bg-[var(--color-panel-raised)]"
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

        {/* Chart */}
        <div ref={scrollRef} className="overflow-x-auto">
          <div className="relative" style={{ width, minWidth: '100%' }}>
            {/* Header: month band + day cells (daily) or tick labels (coarse) */}
            <div
              className="relative border-b border-[var(--color-line)]"
              style={{ height: HEADER_HEIGHT, width }}
            >
              {daily ? (
                <>
                  {monthSegments(model).map((segment) => (
                    <span
                      key={`${segment.label}-${segment.left}`}
                      className="absolute top-0 flex h-5 items-center border-l border-[var(--color-line-subtle)] text-[length:var(--text-2xs)] font-semibold whitespace-nowrap text-[var(--color-ink-muted)] first:border-l-0"
                      style={{ left: segment.left, width: segment.width }}
                    >
                      {/* Sticky: the label stays readable while its month scrolls. */}
                      <span className="sticky left-0 pl-2">
                        {segment.width > 70 ? segment.label : ''}
                      </span>
                    </span>
                  ))}
                  {days.map((day, index) => {
                    const isToday = diffDays(day, today) === 0;
                    return (
                      <span
                        key={day.toISOString()}
                        className={cn(
                          'absolute top-5 bottom-0 flex flex-col items-center justify-center leading-none',
                          isWeekend(day) && 'bg-[var(--color-panel-sunken)]',
                        )}
                        style={{ left: index * model.pixelsPerDay, width: model.pixelsPerDay }}
                      >
                        <span
                          className={cn(
                            'text-[9px] uppercase',
                            isToday
                              ? 'font-semibold text-[var(--color-brand)]'
                              : 'text-[var(--color-ink-subtle)]',
                          )}
                        >
                          {day.toLocaleDateString('de-DE', { weekday: 'short' })}
                        </span>
                        <span
                          className={cn(
                            'tabular mt-0.5 flex size-5 items-center justify-center rounded-full text-[length:var(--text-2xs)]',
                            isToday
                              ? 'bg-[var(--color-brand)] font-semibold text-white'
                              : 'font-medium text-[var(--color-ink)]',
                          )}
                        >
                          {day.getDate()}
                        </span>
                      </span>
                    );
                  })}
                </>
              ) : (
                ticks.map((tick) => (
                  <span
                    key={tick.toISOString()}
                    className="absolute inset-y-0 flex items-center border-l border-[var(--color-line-subtle)] pl-2 text-[length:var(--text-2xs)] whitespace-nowrap text-[var(--color-ink-muted)] first:border-l-0"
                    style={{ left: diffDays(model.start, tick) * model.pixelsPerDay }}
                  >
                    {tick.toLocaleDateString('de-DE', {
                      day: '2-digit',
                      month: 'short',
                      year: model.totalDays > 180 ? '2-digit' : undefined,
                    })}
                  </span>
                ))
              )}
            </div>

            {/* Body: weekend bands, grid lines, bars */}
            <div className="relative" style={{ height: bodyHeight, width }}>
              {daily
                ? days.map((day, index) =>
                    isWeekend(day) ? (
                      <span
                        key={`weekend-${day.toISOString()}`}
                        className="absolute inset-y-0 bg-[var(--color-panel-sunken)]/60"
                        style={{ left: index * model.pixelsPerDay, width: model.pixelsPerDay }}
                        aria-hidden
                      />
                    ) : null,
                  )
                : null}
              {ticks.map((tick) => (
                <span
                  key={`grid-${tick.toISOString()}`}
                  className={cn(
                    'absolute inset-y-0 border-l',
                    daily && tick.getDay() === 1
                      ? 'border-[var(--color-line)]'
                      : 'border-[var(--color-line-subtle)]',
                  )}
                  style={{ left: diffDays(model.start, tick) * model.pixelsPerDay }}
                  aria-hidden
                />
              ))}

              {model.scheduled.map(({ task, start, end }, rowIndex) => {
                const left = diffDays(model.start, start) * model.pixelsPerDay;
                const barWidth = Math.max((diffDays(start, end) + 1) * model.pixelsPerDay - 6, 18);
                return (
                  <div
                    key={task.id}
                    className="absolute right-0 left-0 border-b border-[var(--color-line-subtle)] last:border-b-0"
                    style={{ top: rowIndex * ROW_HEIGHT, height: ROW_HEIGHT }}
                  >
                    <button
                      type="button"
                      onClick={() => onOpenTask(task.id)}
                      className="absolute top-1/2 flex h-7 -translate-y-1/2 items-center overflow-hidden rounded-[var(--radius-md)] px-2.5 text-left text-[length:var(--text-2xs)] font-semibold whitespace-nowrap text-white shadow-[var(--shadow-panel)] transition-[filter,box-shadow] hover:shadow-[var(--shadow-popover)] hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-brand)]"
                      style={{
                        left: left + 3,
                        width: barWidth,
                        backgroundColor: `var(--color-status-${STATUS_TONES[task.status]})`,
                      }}
                      aria-label={`${task.title}: ${start.toLocaleDateString('de-DE')} bis ${end.toLocaleDateString('de-DE')}, ${TASK_STATUS_LABELS[task.status]}`}
                      title={`${task.title} · ${start.toLocaleDateString('de-DE')} – ${end.toLocaleDateString('de-DE')}`}
                    >
                      {barWidth >= 80 ? task.title : ''}
                    </button>
                  </div>
                );
              })}

              {showToday ? (
                <span
                  className="pointer-events-none absolute inset-y-0 z-10 w-0.5 -translate-x-1/2 rounded-full bg-[var(--color-brand)]"
                  style={{ left: todayOffset + model.pixelsPerDay / 2 }}
                  aria-hidden
                />
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {model.undated.length > 0 ? (
        <div className="border-t border-[var(--color-line-subtle)] bg-[var(--color-panel-sunken)] px-3 py-2.5">
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
