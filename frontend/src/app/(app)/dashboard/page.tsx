'use client';

import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  BadgeEuro,
  CheckCircle2,
  Circle,
  Database,
  FolderKanban,
  ListChecks,
  PlugZap,
  Receipt,
  Timer,
  XCircle,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import * as React from 'react';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { PageHeader } from '@/components/layout/app-shell';
import {
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelTitle,
  StatTile,
} from '@/components/ui/panel';
import { PriorityPill, StatusTint } from '@/components/ui/status-pill';
import { useInvoices } from '@/lib/api/invoicing';
import { PRIORITY_LABELS, useProjects, useTasks, type Task } from '@/lib/api/projects';
import { systemApi } from '@/lib/api/system';
import { useTimeEntriesRange } from '@/lib/api/time';
import { useSession } from '@/lib/session';
import { formatHours, formatMoney } from '@/lib/utils';

const CHART_DAYS = 14;

/** Local midnight `offset` days before today. */
function dayStart(offset: number): Date {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - offset);
  return date;
}

/**
 * Übersicht: der Arbeitstag auf einen Blick.
 *
 * Alles hier ist ein Absprungpunkt — jede Kachel und jede Zeile verlinkt auf
 * die Seite, auf der man handeln kann. Reine Zierde (Firmenprofil) ist in die
 * Einstellungen gewandert; der Systemstatus bleibt als kompakte Karte.
 */
export default function DashboardPage() {
  const router = useRouter();
  const { data: session } = useSession();

  // Stable per mount: a changing `new Date()` in the query key would refetch
  // on every render. Day granularity is enough for a dashboard.
  const range = React.useMemo(
    () => ({
      time_from: dayStart(CHART_DAYS - 1).toISOString(),
      time_to: dayStart(-1).toISOString(),
    }),
    [],
  );
  const { entries, isLoading: timeLoading } = useTimeEntriesRange(range);

  const projectsQuery = useProjects({ status: 'active' });
  const tasksQuery = useTasks({ assigned_to_me: true });
  const invoicesQuery = useInvoices();

  const readiness = useQuery({
    queryKey: ['system', 'readiness'],
    queryFn: systemApi.readiness,
    refetchInterval: 60_000,
  });
  const version = useQuery({
    queryKey: ['system', 'version'],
    queryFn: systemApi.version,
    staleTime: Infinity,
  });

  // --- Aggregations -------------------------------------------------------

  const chartData = React.useMemo(() => {
    const byDay = new Map<string, number>();
    for (const entry of entries) {
      const key = new Date(entry.started_at).toDateString();
      byDay.set(key, (byDay.get(key) ?? 0) + entry.duration_seconds);
    }
    return Array.from({ length: CHART_DAYS }, (_, index) => {
      const date = dayStart(CHART_DAYS - 1 - index);
      return {
        label: date.toLocaleDateString('de-DE', { weekday: 'short' }),
        date: date.toLocaleDateString('de-DE', { day: 'numeric', month: 'numeric' }),
        hours: Math.round(((byDay.get(date.toDateString()) ?? 0) / 3600) * 100) / 100,
      };
    });
  }, [entries]);

  const chartTotal = chartData.reduce((sum, day) => sum + day.hours, 0);

  const weekHours = React.useMemo(() => {
    const today = dayStart(0);
    const monday = dayStart((today.getDay() + 6) % 7);
    return (
      entries
        .filter((entry) => new Date(entry.started_at) >= monday)
        .reduce((sum, entry) => sum + entry.duration_seconds, 0) / 3600
    );
  }, [entries]);

  const activeProjects = React.useMemo(() => {
    const list = projectsQuery.data?.results ?? [];
    return [...list].sort(
      (a, b) => Number(b.stats.time.unbilled_value) - Number(a.stats.time.unbilled_value),
    );
  }, [projectsQuery.data]);

  const unbilledTotal = activeProjects.reduce(
    (sum, project) => sum + Number(project.stats.time.unbilled_value),
    0,
  );

  const myTasks = React.useMemo(() => {
    const list = (tasksQuery.data?.results ?? []).filter((task) => task.status !== 'done');
    return [...list].sort((a, b) => (a.due_date ?? '9999').localeCompare(b.due_date ?? '9999'));
  }, [tasksQuery.data]);

  const overdueCount = myTasks.filter(
    (task) => task.due_date && new Date(task.due_date) < dayStart(0),
  ).length;

  const openReceivables = (invoicesQuery.data?.results ?? [])
    .filter((invoice) => invoice.status === 'open' || invoice.status === 'overdue')
    .reduce((sum, invoice) => sum + Number(invoice.open_amount), 0);

  const integrations = readiness.data?.checks.integrations;
  const today = new Intl.DateTimeFormat('de-DE', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date());

  const openTask = (task: Task) => router.push(`/boards/${task.board}?task=${task.id}`);

  return (
    <>
      <PageHeader
        title={`Willkommen, ${session?.user.first_name || session?.user.email.split('@')[0] || ''}`}
        description={`${today}${session?.workspace ? ` · ${session.workspace.name}` : ''}`}
      />

      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Link href="/time" className="min-w-0">
            <StatTile
              icon={<Timer />}
              label="Diese Woche"
              value={timeLoading ? '…' : formatHours(weekHours)}
              hint="Erfasste Zeit"
              className="transition-shadow hover:shadow-[var(--shadow-popover)]"
            />
          </Link>
          <Link href="/projects" className="min-w-0">
            <StatTile
              icon={<BadgeEuro />}
              label="Noch abzurechnen"
              value={projectsQuery.isLoading ? '…' : formatMoney(unbilledTotal.toFixed(2))}
              hint="Offene Zeiten aktiver Projekte"
              tone={unbilledTotal > 0 ? 'warning' : 'default'}
              className="transition-shadow hover:shadow-[var(--shadow-popover)]"
            />
          </Link>
          <Link href="/invoices" className="min-w-0">
            <StatTile
              icon={<Receipt />}
              label="Offene Forderungen"
              value={invoicesQuery.isLoading ? '…' : formatMoney(openReceivables.toFixed(2))}
              hint="Versendete Rechnungen"
              tone={openReceivables > 0 ? 'warning' : 'default'}
              className="transition-shadow hover:shadow-[var(--shadow-popover)]"
            />
          </Link>
          <Link href="/my-tasks" className="min-w-0">
            <StatTile
              icon={<ListChecks />}
              label="Meine Aufgaben"
              value={tasksQuery.isLoading ? '…' : myTasks.length}
              hint={overdueCount > 0 ? `${overdueCount} überfällig` : 'Nichts überfällig'}
              tone={overdueCount > 0 ? 'danger' : 'default'}
              className="transition-shadow hover:shadow-[var(--shadow-popover)]"
            />
          </Link>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <Panel>
              <PanelHeader>
                <div>
                  <PanelTitle>Erfasste Zeit</PanelTitle>
                  <p className="mt-0.5 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
                    Letzte {CHART_DAYS} Tage · {formatHours(chartTotal)}
                  </p>
                </div>
                <Link
                  href="/time"
                  className="inline-flex items-center gap-1 text-[length:var(--text-xs)] font-medium text-[var(--color-brand)] hover:underline"
                >
                  Zur Zeiterfassung <ArrowRight className="size-3" aria-hidden />
                </Link>
              </PanelHeader>
              <PanelBody>
                {timeLoading ? (
                  <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
                    Lädt…
                  </p>
                ) : chartTotal === 0 ? (
                  <EmptyState
                    icon={<Timer className="size-8" aria-hidden />}
                    title="Noch keine Zeiten"
                    description="Starte den Timer oder erfasse Zeiten manuell — hier erscheint dann dein Verlauf."
                  />
                ) : (
                  <div className="h-56 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData} margin={{ top: 4, left: -12, right: 0 }}>
                        <XAxis
                          dataKey="label"
                          axisLine={false}
                          tickLine={false}
                          stroke="var(--color-ink-subtle)"
                          fontSize={11}
                          minTickGap={4}
                        />
                        <YAxis
                          axisLine={false}
                          tickLine={false}
                          stroke="var(--color-ink-subtle)"
                          fontSize={11}
                          allowDecimals={false}
                          tickFormatter={(value: number) => `${value}h`}
                        />
                        <Tooltip
                          cursor={{ fill: 'var(--color-panel-raised)' }}
                          contentStyle={{
                            background: 'var(--color-panel)',
                            border: '1px solid var(--color-line)',
                            borderRadius: 10,
                            fontSize: 12,
                            boxShadow: 'var(--shadow-popover)',
                          }}
                          formatter={(value) => [formatHours(Number(value)), 'Erfasst']}
                          labelFormatter={(_, payload) => {
                            const day = payload?.[0]?.payload as
                              { label: string; date: string } | undefined;
                            return day ? `${day.label} ${day.date}` : '';
                          }}
                        />
                        <Bar
                          dataKey="hours"
                          fill="var(--color-brand)"
                          radius={[4, 4, 0, 0]}
                          maxBarSize={22}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </PanelBody>
            </Panel>

            <Panel>
              <PanelHeader>
                <PanelTitle>Aktive Projekte</PanelTitle>
                <Link
                  href="/projects"
                  className="inline-flex items-center gap-1 text-[length:var(--text-xs)] font-medium text-[var(--color-brand)] hover:underline"
                >
                  Alle Projekte <ArrowRight className="size-3" aria-hidden />
                </Link>
              </PanelHeader>
              <PanelBody className="p-2">
                {projectsQuery.isLoading ? (
                  <p className="p-2 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
                    Lädt…
                  </p>
                ) : activeProjects.length === 0 ? (
                  <EmptyState
                    icon={<FolderKanban className="size-8" aria-hidden />}
                    title="Keine aktiven Projekte"
                    description="Lege ein Projekt an, um Aufgaben und Zeiten zu verplanen."
                  />
                ) : (
                  <ul>
                    {activeProjects.slice(0, 5).map((project) => {
                      const total = project.stats.tasks.total;
                      const percent =
                        total > 0
                          ? Math.round((project.stats.tasks.done / total) * 100)
                          : project.progress;
                      return (
                        <li key={project.id}>
                          <Link
                            href={`/projects/${project.id}`}
                            className="block rounded-[var(--radius-md)] px-2.5 py-2.5 transition-colors hover:bg-[var(--color-panel-raised)]"
                          >
                            <div className="flex items-center gap-2.5">
                              <span
                                className="size-2.5 shrink-0 rounded-full"
                                style={{ backgroundColor: project.color }}
                                aria-hidden
                              />
                              <span className="min-w-0 flex-1 truncate text-[length:var(--text-sm)] font-medium">
                                {project.name}
                              </span>
                              <span className="hidden shrink-0 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)] sm:block">
                                {project.client_name}
                              </span>
                              {Number(project.stats.time.unbilled_value) > 0 ? (
                                <span className="tabular shrink-0 text-[length:var(--text-xs)] font-medium text-[var(--color-warning)]">
                                  {formatMoney(project.stats.time.unbilled_value)} offen
                                </span>
                              ) : null}
                            </div>
                            <div className="mt-2 flex items-center gap-2.5 pl-5">
                              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--color-panel-sunken)]">
                                <div
                                  className="h-full rounded-full bg-[var(--color-brand)]"
                                  style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
                                />
                              </div>
                              <span className="tabular shrink-0 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                                {total > 0
                                  ? `${project.stats.tasks.done}/${total} Aufgaben`
                                  : `${percent} %`}
                              </span>
                            </div>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </PanelBody>
            </Panel>
          </div>

          <div className="space-y-4">
            <Panel>
              <PanelHeader>
                <PanelTitle>Meine nächsten Aufgaben</PanelTitle>
                <Link
                  href="/my-tasks"
                  className="inline-flex items-center gap-1 text-[length:var(--text-xs)] font-medium text-[var(--color-brand)] hover:underline"
                >
                  Alle <ArrowRight className="size-3" aria-hidden />
                </Link>
              </PanelHeader>
              <PanelBody className="p-2">
                {tasksQuery.isLoading ? (
                  <p className="p-2 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
                    Lädt…
                  </p>
                ) : myTasks.length === 0 ? (
                  <EmptyState
                    icon={<ListChecks className="size-8" aria-hidden />}
                    title="Alles erledigt"
                    description="Dir ist aktuell keine offene Aufgabe zugewiesen."
                  />
                ) : (
                  <ul>
                    {myTasks.slice(0, 6).map((task) => {
                      const overdue = task.due_date && new Date(task.due_date) < dayStart(0);
                      return (
                        <li key={task.id}>
                          <button
                            type="button"
                            onClick={() => openTask(task)}
                            className="block w-full rounded-[var(--radius-md)] px-2.5 py-2 text-left transition-colors hover:bg-[var(--color-panel-raised)]"
                          >
                            <div className="truncate text-[length:var(--text-sm)] font-medium">
                              {task.title}
                            </div>
                            <div className="mt-1 flex items-center gap-2">
                              <PriorityPill tone={task.priority}>
                                {PRIORITY_LABELS[task.priority]}
                              </PriorityPill>
                              <span className="min-w-0 flex-1 truncate text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                                {task.project_name}
                              </span>
                              {task.due_date ? (
                                <span
                                  className={
                                    overdue
                                      ? 'shrink-0 text-[length:var(--text-2xs)] font-medium text-[var(--color-danger)]'
                                      : 'shrink-0 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]'
                                  }
                                >
                                  {new Date(task.due_date).toLocaleDateString('de-DE', {
                                    day: 'numeric',
                                    month: 'numeric',
                                  })}
                                </span>
                              ) : null}
                            </div>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </PanelBody>
            </Panel>

            <Panel>
              <PanelHeader>
                <PanelTitle>System</PanelTitle>
              </PanelHeader>
              <PanelBody className="space-y-2.5">
                <StatusRow
                  icon={<Database className="size-4" aria-hidden />}
                  label="Datenbank"
                  ok={readiness.data?.checks.database.status === 'ok'}
                  loading={readiness.isLoading}
                />
                <StatusRow
                  icon={<Database className="size-4" aria-hidden />}
                  label="Cache"
                  ok={readiness.data?.checks.cache.status === 'ok'}
                  loading={readiness.isLoading}
                />
                <div className="border-t border-[var(--color-line-subtle)] pt-2.5">
                  <div className="mb-2 flex items-center gap-1.5 text-[length:var(--text-xs)] font-medium text-[var(--color-ink-muted)]">
                    <PlugZap className="size-3.5" aria-hidden />
                    Integrationen
                  </div>
                  <div className="space-y-1.5">
                    <IntegrationRow name="Lexware Office" state={integrations?.lexware} />
                    <IntegrationRow name="Clockify" state={integrations?.clockify} />
                  </div>
                </div>
                {version.data ? (
                  <div className="border-t border-[var(--color-line-subtle)] pt-2.5 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    v{version.data.version} · {version.data.environment} · {version.data.time_zone}
                  </div>
                ) : null}
              </PanelBody>
            </Panel>
          </div>
        </div>
      </div>
    </>
  );
}

function StatusRow({
  icon,
  label,
  ok,
  loading,
}: {
  icon: React.ReactNode;
  label: string;
  ok: boolean;
  loading: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[var(--color-ink-subtle)]">{icon}</span>
      <span className="flex-1 text-[length:var(--text-sm)]">{label}</span>
      {loading ? (
        <Circle
          className="size-4 animate-pulse text-[var(--color-ink-subtle)]"
          aria-label="Prüfe"
        />
      ) : ok ? (
        <CheckCircle2 className="size-4 text-[var(--color-success)]" aria-label="OK" />
      ) : (
        <XCircle className="size-4 text-[var(--color-danger)]" aria-label="Fehler" />
      )}
    </div>
  );
}

function IntegrationRow({ name, state }: { name: string; state?: 'enabled' | 'disabled' }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[length:var(--text-sm)]">{name}</span>
      {state === 'enabled' ? (
        <StatusTint tone="done">Aktiv</StatusTint>
      ) : (
        <StatusTint tone="hold">Deaktiviert</StatusTint>
      )}
    </div>
  );
}
