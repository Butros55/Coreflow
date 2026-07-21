'use client';

import {
  ArrowLeft,
  Clock3,
  ListChecks,
  Pencil,
  Plus,
  ReceiptText,
  SquareKanban,
  Trash2,
  UserRound,
} from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { InvoiceStatusBadge } from '@/components/invoices/invoice-status-badge';
import { PageHeader } from '@/components/layout/app-shell';
import { ProjectPlanningTab } from '@/components/projects/planning-tab';
import { ProjectFormDialog } from '@/components/projects/project-form-dialog';
import { CreateTaskDialog } from '@/components/tasks/create-task-dialog';
import { TaskTimeline } from '@/components/tasks/task-timeline';
import { BillingBadge } from '@/components/time/billing-badge';
import { AvatarStack } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { DeleteConfirmationDialog } from '@/components/ui/delete-confirmation-dialog';
import { DetailErrorState } from '@/components/ui/detail-error';
import { ClickableRow, DataTable, Td, Th } from '@/components/ui/group-bar';
import {
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelTitle,
  StatTile,
} from '@/components/ui/panel';
import { PriorityPill, StatusTint } from '@/components/ui/status-pill';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useInvoices, type InvoiceListItem } from '@/lib/api/invoicing';
import {
  BILLING_MODEL_LABELS,
  PRIORITY_LABELS,
  PROJECT_STATUS_LABELS,
  TASK_STATUS_LABELS,
  useProject,
  useDeleteProject,
  useSprints,
  useTasks,
  type Project,
  type Task,
} from '@/lib/api/projects';
import { useTimeEntries, type TimeEntry } from '@/lib/api/time';
import { usePermissions } from '@/lib/session';
import { formatHours, formatMoney } from '@/lib/utils';

const TASK_TONES = {
  todo: 'todo',
  in_progress: 'progress',
  review: 'review',
  done: 'done',
  stuck: 'stuck',
} as const;

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const permissions = usePermissions();
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  const [createTaskOpen, setCreateTaskOpen] = React.useState(false);
  const [taskDefaults, setTaskDefaults] = React.useState<{
    sprint?: string | null;
    phase?: string | null;
  }>({});
  const deleteProject = useDeleteProject();
  const { data: project, isLoading, error } = useProject(params.id);
  const { data: tasksData } = useTasks({ project: params.id });
  const { data: timeData } = useTimeEntries({ project: params.id });
  const { data: invoiceData } = useInvoices({ project: params.id });
  const { data: sprintsData } = useSprints(params.id);

  const openCreateTask = React.useCallback(
    (defaults: { sprint?: string | null; phase?: string | null } = {}) => {
      setTaskDefaults(defaults);
      setCreateTaskOpen(true);
    },
    [],
  );

  if (isLoading) {
    return (
      <div className="p-5 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</div>
    );
  }
  if (error || !project) {
    return (
      <DetailErrorState
        error={error}
        entityLabel="Projekt"
        backHref="/projects"
        backLabel="Alle Projekte"
      />
    );
  }

  const tasks = tasksData?.results ?? [];
  const entries = timeData?.results ?? [];
  const invoices = invoiceData?.results ?? [];
  const sprints = sprintsData?.results ?? [];
  const openTasks = tasks.filter((task) => task.status !== 'done');
  const time = project.stats.time;
  const invoiceStats = project.stats.invoices;
  const loggedHours = time.total_seconds / 3600;
  const budgetHours = project.budget_hours ? Number(project.budget_hours) : null;
  const remainingHours = budgetHours === null ? null : budgetHours - loggedHours;
  const budgetAmount = project.budget_amount ? Number(project.budget_amount) : null;
  const spentAmount = Number(time.total_value);
  const remainingAmount = budgetAmount === null ? null : budgetAmount - spentAmount;

  const openTask = (taskId: string) => {
    const task = tasks.find((candidate) => candidate.id === taskId);
    const board = task?.board ?? project.default_board;
    if (board) router.push(`/boards/${board}?task=${taskId}`);
  };

  return (
    <>
      <PageHeader
        title={project.name}
        description={`${project.client_name} · ${BILLING_MODEL_LABELS[project.billing_model]}`}
        actions={
          <div className="flex items-center gap-2">
            <StatusTint tone={project.status === 'active' ? 'done' : 'hold'}>
              {PROJECT_STATUS_LABELS[project.status]}
            </StatusTint>
            {permissions.can_write && project.default_board ? (
              <Button variant="primary" size="sm" onClick={() => openCreateTask({})}>
                <Plus aria-hidden /> Neue Aufgabe
              </Button>
            ) : null}
            {project.default_board ? (
              <Button variant="secondary" size="sm" asChild>
                <Link href={`/boards/${project.default_board}`}>
                  <SquareKanban aria-hidden /> Zum Board
                </Link>
              </Button>
            ) : null}
            {permissions.can_write ? (
              <Button variant="ghost" size="sm" onClick={() => setEditOpen(true)}>
                <Pencil aria-hidden /> Bearbeiten
              </Button>
            ) : null}
            {permissions.can_write ? (
              <Button
                variant="ghost"
                size="sm"
                className="text-[var(--color-danger)]"
                onClick={() => setDeleteOpen(true)}
              >
                <Trash2 aria-hidden /> Löschen
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" asChild>
              <Link href="/projects">
                <ArrowLeft aria-hidden /> Alle Projekte
              </Link>
            </Button>
          </div>
        }
      >
        <div className="pb-4" />
      </PageHeader>

      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <StatTile
            label="Offene Aufgaben"
            value={project.stats.tasks.open}
            hint={
              project.stats.tasks.overdue > 0
                ? `${project.stats.tasks.overdue} überfällig`
                : `${project.stats.tasks.done} erledigt`
            }
            tone={project.stats.tasks.overdue > 0 ? 'danger' : 'default'}
          />
          <StatTile
            label="Erfasste Zeit"
            value={formatHours(loggedHours)}
            hint={budgetHours !== null ? `von ${formatHours(budgetHours)}` : 'Ohne Stundenbudget'}
            tone={remainingHours !== null && remainingHours < 0 ? 'danger' : 'default'}
          />
          <StatTile
            label="Noch abzurechnen"
            value={formatHours(time.unbilled_seconds / 3600)}
            hint={formatMoney(time.unbilled_value)}
            tone={time.unbilled_seconds > 0 ? 'warning' : 'default'}
          />
          <StatTile
            label="Abgerechnet"
            value={formatHours(time.billed_seconds / 3600)}
            hint={formatMoney(time.billed_value)}
          />
          <StatTile
            label="Bezahlt"
            value={formatHours(time.paid_seconds / 3600)}
            hint={`${formatMoney(time.paid_value)} aus Zeiteinträgen`}
            tone={time.paid_seconds > 0 ? 'success' : 'default'}
          />
          <StatTile
            label={remainingAmount === null ? 'Projektwert' : 'Restbudget'}
            value={
              remainingAmount === null
                ? formatMoney(time.total_value)
                : formatMoney(Math.abs(remainingAmount))
            }
            hint={
              remainingAmount === null
                ? `${invoiceStats.total_count} Rechnungen`
                : remainingAmount < 0
                  ? 'Budget überschritten'
                  : `von ${formatMoney(budgetAmount)}`
            }
            tone={remainingAmount !== null && remainingAmount < 0 ? 'danger' : 'default'}
          />
        </div>

        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">Übersicht</TabsTrigger>
            <TabsTrigger value="tasks">Aufgaben ({tasks.length})</TabsTrigger>
            <TabsTrigger value="billing">Zeiten & Abrechnung</TabsTrigger>
            <TabsTrigger value="planning">Planung & Details</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="pt-4">
            <OverviewTab
              project={project}
              openTasks={openTasks}
              onOpenTask={openTask}
              remainingHours={remainingHours}
              remainingAmount={remainingAmount}
            />
          </TabsContent>

          <TabsContent value="tasks" className="space-y-3 pt-4">
            {permissions.can_write && project.default_board ? (
              <div className="flex justify-end">
                <Button variant="secondary" size="sm" onClick={() => openCreateTask({})}>
                  <Plus aria-hidden /> Neue Aufgabe
                </Button>
              </div>
            ) : null}
            <TaskTable
              tasks={tasks}
              onOpenTask={openTask}
              onCreate={
                permissions.can_write && project.default_board
                  ? () => openCreateTask({})
                  : undefined
              }
            />
          </TabsContent>

          <TabsContent value="billing" className="space-y-4 pt-4">
            <BillingTab project={project} entries={entries} invoices={invoices} />
          </TabsContent>

          <TabsContent value="planning" className="space-y-4 pt-4">
            <TaskTimeline tasks={tasks} onOpenTask={openTask} />
            <ProjectPlanningTab
              project={project}
              sprints={sprints}
              tasks={tasks}
              canEdit={permissions.can_write}
              onOpenTask={openTask}
              onCreateTask={openCreateTask}
            />
          </TabsContent>
        </Tabs>
      </div>
      <ProjectFormDialog open={editOpen} onOpenChange={setEditOpen} project={project} />
      {project.default_board ? (
        <CreateTaskDialog
          open={createTaskOpen}
          onOpenChange={setCreateTaskOpen}
          projectId={project.id}
          boardId={project.default_board}
          defaultSprint={taskDefaults.sprint ?? null}
          defaultPhase={taskDefaults.phase ?? null}
        />
      ) : null}
      <DeleteConfirmationDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Projekt löschen?"
        itemName={project.name}
        message="Alle Boards, Aufgaben, Checklisten, Kommentare und angehängten Dateien dieses Projekts werden gelöscht. Erfasste Zeiten und Rechnungen bleiben erhalten, verlieren aber ihre Projektzuordnung."
        isPending={deleteProject.isPending}
        onConfirm={() =>
          deleteProject.mutate(project.id, {
            onSuccess: () => {
              toast.success(`Projekt „${project.name}“ gelöscht.`);
              router.replace('/projects');
            },
            onError: (deleteError) => toast.error(deleteError.message),
          })
        }
      />
    </>
  );
}

function OverviewTab({
  project,
  openTasks,
  onOpenTask,
  remainingHours,
  remainingAmount,
}: {
  project: Project;
  openTasks: Task[];
  onOpenTask: (id: string) => void;
  remainingHours: number | null;
  remainingAmount: number | null;
}) {
  const time = project.stats.time;
  return (
    <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
      <div className="space-y-4">
        <Panel>
          <PanelHeader>
            <PanelTitle>Leistung & Abrechnung</PanelTitle>
            <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
              {formatHours(time.billable_seconds / 3600)} abrechenbar
            </span>
          </PanelHeader>
          <PanelBody className="space-y-4">
            <FlowRow
              label="Offen"
              seconds={time.unbilled_seconds}
              amount={time.unbilled_value}
              total={time.billable_seconds}
              color="var(--color-status-todo)"
            />
            <FlowRow
              label="Im Rechnungsentwurf"
              seconds={time.draft_seconds}
              amount={time.draft_value}
              total={time.billable_seconds}
              color="var(--color-status-progress)"
            />
            <FlowRow
              label="Abgerechnet"
              seconds={time.billed_seconds}
              amount={time.billed_value}
              total={time.billable_seconds}
              color="var(--color-status-review)"
            />
            <FlowRow
              label="Davon bezahlt"
              seconds={time.paid_seconds}
              amount={time.paid_value}
              total={time.billable_seconds}
              color="var(--color-success)"
            />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Offene Aufgaben</PanelTitle>
            <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
              {openTasks.length} offen
            </span>
          </PanelHeader>
          {openTasks.length === 0 ? (
            <PanelBody>
              <EmptyState
                icon={<ListChecks className="size-7" aria-hidden />}
                title="Alle Aufgaben erledigt"
              />
            </PanelBody>
          ) : (
            <DataTable>
              <tbody>
                {openTasks.slice(0, 8).map((task) => (
                  <ClickableRow key={task.id} onClick={() => onOpenTask(task.id)}>
                    <Td className="font-medium">{task.title}</Td>
                    <Td>
                      <StatusTint tone={TASK_TONES[task.status]}>
                        {TASK_STATUS_LABELS[task.status]}
                      </StatusTint>
                    </Td>
                    <Td>
                      <AvatarStack users={task.assignee_details} size="sm" />
                    </Td>
                    <Td className="tabular text-right text-[var(--color-ink-muted)]">
                      {dateLabel(task.due_date)}
                    </Td>
                  </ClickableRow>
                ))}
              </tbody>
            </DataTable>
          )}
        </Panel>
      </div>

      <div className="space-y-4">
        <Panel>
          <PanelHeader>
            <PanelTitle>Projektsteckbrief</PanelTitle>
          </PanelHeader>
          <PanelBody className="space-y-4">
            <Link
              href={`/clients/${project.client}`}
              className="flex items-center gap-3 rounded-[var(--radius-md)] bg-[var(--color-panel-sunken)] p-3 transition-colors hover:bg-[var(--color-panel-raised)]"
            >
              <div className="flex size-9 items-center justify-center rounded-full bg-[var(--color-brand-subtle)] text-[var(--color-brand)]">
                <UserRound className="size-4" aria-hidden />
              </div>
              <div className="min-w-0">
                <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                  Kunde
                </div>
                <div className="truncate font-medium">{project.client_name}</div>
              </div>
            </Link>
            <dl className="grid grid-cols-2 gap-3 text-[length:var(--text-sm)]">
              <Detail
                label="Abrechnungsmodell"
                value={BILLING_MODEL_LABELS[project.billing_model]}
              />
              <Detail label="Projektleitung" value={project.lead?.full_name ?? '—'} />
              <Detail label="Start" value={dateLabel(project.start_date)} />
              <Detail label="Zieldatum" value={dateLabel(project.target_date)} />
              <Detail
                label="Stundensatz"
                value={
                  project.default_hourly_rate
                    ? formatMoney(project.default_hourly_rate)
                    : 'Kunden-/Workspace-Standard'
                }
              />
              <Detail label="Fortschritt" value={`${project.progress} %`} />
            </dl>
            {project.description ? (
              <p className="text-[length:var(--text-sm)] whitespace-pre-wrap text-[var(--color-ink-muted)]">
                {project.description}
              </p>
            ) : null}
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Budgets</PanelTitle>
          </PanelHeader>
          <PanelBody className="space-y-4">
            <BudgetRow
              label="Stundenbudget"
              used={project.stats.time.total_seconds / 3600}
              total={project.budget_hours ? Number(project.budget_hours) : null}
              remaining={remainingHours}
              formatter={formatHours}
            />
            <BudgetRow
              label="Kostenbudget"
              used={Number(project.stats.time.total_value)}
              total={project.budget_amount ? Number(project.budget_amount) : null}
              remaining={remainingAmount}
              formatter={formatMoney}
            />
          </PanelBody>
        </Panel>
      </div>
    </div>
  );
}

function TaskTable({
  tasks,
  onOpenTask,
  onCreate,
}: {
  tasks: Task[];
  onOpenTask: (id: string) => void;
  onCreate?: () => void;
}) {
  if (tasks.length === 0) {
    return (
      <EmptyState
        icon={<ListChecks className="size-8" />}
        title="Noch keine Aufgaben"
        description="Aufgaben werden automatisch diesem Projekt und Kunden zugeordnet."
        action={
          onCreate ? (
            <Button variant="primary" size="sm" onClick={onCreate}>
              <Plus aria-hidden /> Erste Aufgabe anlegen
            </Button>
          ) : undefined
        }
      />
    );
  }
  return (
    <Panel>
      <DataTable>
        <thead>
          <tr>
            <Th className="w-[35%]">Aufgabe</Th>
            <Th>Status</Th>
            <Th>Priorität</Th>
            <Th>Verantwortlich</Th>
            <Th>Fällig</Th>
            <Th className="text-right">Erfasst</Th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <ClickableRow key={task.id} onClick={() => onOpenTask(task.id)}>
              <Td>
                <div className="font-medium">{task.title}</div>
                {task.parent_title ? (
                  <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    Unteraufgabe von {task.parent_title}
                  </div>
                ) : null}
              </Td>
              <Td>
                <StatusTint tone={TASK_TONES[task.status]}>
                  {TASK_STATUS_LABELS[task.status]}
                </StatusTint>
              </Td>
              <Td>
                <PriorityPill tone={task.priority}>{PRIORITY_LABELS[task.priority]}</PriorityPill>
              </Td>
              <Td>
                <AvatarStack users={task.assignee_details} size="sm" />
              </Td>
              <Td className={isOverdue(task) ? 'font-medium text-[var(--color-danger)]' : ''}>
                {dateLabel(task.due_date)}
              </Td>
              <Td className="tabular text-right">{formatHours(task.logged_seconds / 3600)}</Td>
            </ClickableRow>
          ))}
        </tbody>
      </DataTable>
    </Panel>
  );
}

function BillingTab({
  project,
  entries,
  invoices,
}: {
  project: Project;
  entries: TimeEntry[];
  invoices: InvoiceListItem[];
}) {
  const stats = project.stats.invoices;
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Fakturiert (netto)"
          value={formatMoney(stats.invoiced_net)}
          hint={`${stats.total_count} Rechnungen`}
        />
        <StatTile
          label="Offene Forderungen (brutto)"
          value={formatMoney(stats.open_gross)}
          tone={Number(stats.open_gross) > 0 ? 'warning' : 'default'}
        />
        <StatTile
          label="Bezahlt (netto)"
          value={formatMoney(stats.paid_net)}
          hint={`${stats.paid_count} bezahlt`}
          tone={stats.paid_count > 0 ? 'success' : 'default'}
        />
        <StatTile
          label="Überfällige Rechnungen"
          value={stats.overdue_count}
          tone={stats.overdue_count > 0 ? 'danger' : 'default'}
        />
      </div>
      <Panel>
        <PanelHeader>
          <PanelTitle>Zeiteinträge</PanelTitle>
          <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            {entries.length} Einträge
          </span>
        </PanelHeader>
        {entries.length === 0 ? (
          <PanelBody>
            <EmptyState icon={<Clock3 className="size-7" />} title="Noch keine Zeiten" />
          </PanelBody>
        ) : (
          <DataTable>
            <thead>
              <tr>
                <Th>Datum</Th>
                <Th>Beschreibung</Th>
                <Th>Aufgabe</Th>
                <Th>Status</Th>
                <Th className="text-right">Dauer</Th>
                <Th className="text-right">Wert</Th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id} className="last:[&>td]:border-b-0">
                  <Td>{new Date(entry.started_at).toLocaleDateString('de-DE')}</Td>
                  <Td className="font-medium">{entry.description || 'Ohne Beschreibung'}</Td>
                  <Td>{entry.task_title ?? '—'}</Td>
                  <Td>
                    <BillingBadge status={entry.billing_status} />
                  </Td>
                  <Td className="tabular text-right">
                    {formatHours(entry.duration_seconds / 3600)}
                  </Td>
                  <Td className="tabular text-right">
                    {entry.billable ? formatMoney(entry.computed_amount) : '—'}
                  </Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Panel>
      <Panel>
        <PanelHeader>
          <PanelTitle>Rechnungen</PanelTitle>
          <Button variant="ghost" size="xs" asChild>
            <Link href="/invoices">
              <ReceiptText aria-hidden /> Alle Rechnungen
            </Link>
          </Button>
        </PanelHeader>
        {invoices.length === 0 ? (
          <PanelBody>
            <EmptyState icon={<ReceiptText className="size-7" />} title="Noch keine Rechnungen" />
          </PanelBody>
        ) : (
          <DataTable>
            <thead>
              <tr>
                <Th>Nummer</Th>
                <Th>Datum</Th>
                <Th>Status</Th>
                <Th>Fällig</Th>
                <Th className="text-right">Netto</Th>
                <Th className="text-right">Offen</Th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <ClickableRow
                  key={invoice.id}
                  onClick={() => window.location.assign(`/invoices/${invoice.id}`)}
                >
                  <Td className="font-medium">
                    {invoice.invoice_number || `Entwurf ${invoice.id.slice(0, 8)}`}
                  </Td>
                  <Td>{dateLabel(invoice.invoice_date)}</Td>
                  <Td>
                    <InvoiceStatusBadge status={invoice.status} />
                  </Td>
                  <Td>{dateLabel(invoice.due_date)}</Td>
                  <Td className="tabular text-right">{formatMoney(invoice.net_amount)}</Td>
                  <Td className="tabular text-right">{formatMoney(invoice.open_amount)}</Td>
                </ClickableRow>
              ))}
            </tbody>
          </DataTable>
        )}
      </Panel>
    </>
  );
}

function FlowRow({
  label,
  seconds,
  amount,
  total,
  color,
}: {
  label: string;
  seconds: number;
  amount: string;
  total: number;
  color: string;
}) {
  const percentage = total > 0 ? Math.min((seconds / total) * 100, 100) : 0;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-3 text-[length:var(--text-sm)]">
        <span className="font-medium">{label}</span>
        <span className="tabular text-[var(--color-ink-muted)]">
          {formatHours(seconds / 3600)} · {formatMoney(amount)}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[var(--color-panel-sunken)]">
        <div
          className="h-full rounded-full"
          style={{ width: `${percentage}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

function BudgetRow({
  label,
  used,
  total,
  remaining,
  formatter,
}: {
  label: string;
  used: number;
  total: number | null;
  remaining: number | null;
  formatter: (value: number) => string;
}) {
  if (total === null)
    return (
      <div>
        <div className="text-[length:var(--text-sm)] font-medium">{label}</div>
        <div className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
          Kein Budget hinterlegt · genutzt {formatter(used)}
        </div>
      </div>
    );
  const pct = total > 0 ? (used / total) * 100 : 0;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-[length:var(--text-sm)]">
        <span className="font-medium">{label}</span>
        <span
          className={
            remaining !== null && remaining < 0
              ? 'font-medium text-[var(--color-danger)]'
              : 'text-[var(--color-ink-muted)]'
          }
        >
          {remaining !== null && remaining < 0
            ? `${formatter(Math.abs(remaining))} überschritten`
            : `${formatter(remaining ?? 0)} frei`}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[var(--color-panel-sunken)]">
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.min(pct, 100)}%`,
            backgroundColor: pct > 100 ? 'var(--color-danger)' : 'var(--color-brand)',
          }}
        />
      </div>
      <div className="mt-1 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
        {formatter(used)} von {formatter(total)} genutzt
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

function dateLabel(value: string | null): string {
  return value ? new Date(value).toLocaleDateString('de-DE') : '—';
}

function isOverdue(task: Task): boolean {
  if (!task.due_date || task.status === 'done') return false;
  const due = new Date(task.due_date);
  due.setHours(23, 59, 59, 999);
  return due < new Date();
}
