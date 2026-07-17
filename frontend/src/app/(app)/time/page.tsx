'use client';

import {
  ChevronLeft,
  ChevronRight,
  Play,
  Plus,
  Square,
  Timer as TimerIcon,
  Trash2,
} from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/app-shell';
import { BillingBadge } from '@/components/time/billing-badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { DataTable, GroupSection, Td, Th } from '@/components/ui/group-bar';
import { Input, Label } from '@/components/ui/input';
import { EmptyState, Panel, PanelBody, StatTile } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import { useClients } from '@/lib/api/crm';
import { useProjects } from '@/lib/api/projects';
import {
  useCreateTimeEntry,
  useDeleteTimeEntry,
  useServiceTypes,
  useStartTimer,
  useStopTimer,
  useTimeEntries,
  useTimer,
  type TimeEntry,
} from '@/lib/api/time';
import { usePermissions } from '@/lib/session';
import { cn, formatDuration, formatHours, formatMoney } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Week helpers (Monday-based, matching German business convention)
// ---------------------------------------------------------------------------

function startOfWeek(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  const day = (copy.getDay() + 6) % 7; // Monday = 0
  copy.setDate(copy.getDate() - day);
  return copy;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export default function TimePage() {
  const permissions = usePermissions();
  const [weekStart, setWeekStart] = React.useState(() => startOfWeek(new Date()));
  const weekEnd = addDays(weekStart, 7);
  const [createOpen, setCreateOpen] = React.useState(false);

  const { data } = useTimeEntries({
    time_from: weekStart.toISOString(),
    time_to: weekEnd.toISOString(),
  });
  const entries = React.useMemo(
    () => (data?.results ?? []).filter((entry) => !entry.is_running),
    [data],
  );

  const byDay = React.useMemo(() => {
    const map = new Map<string, TimeEntry[]>();
    for (const entry of entries) {
      const key = dayKey(new Date(entry.started_at));
      map.set(key, [...(map.get(key) ?? []), entry]);
    }
    return map;
  }, [entries]);

  const weekSeconds = entries.reduce((sum, entry) => sum + entry.duration_seconds, 0);
  const weekBillable = entries
    .filter((entry) => entry.billable)
    .reduce((sum, entry) => sum + Number(entry.computed_amount), 0);

  const isCurrentWeek = dayKey(weekStart) === dayKey(startOfWeek(new Date()));

  return (
    <>
      <PageHeader
        title="Zeiterfassung"
        actions={
          permissions.can_write ? (
            <Button variant="secondary" onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden /> Manueller Eintrag
            </Button>
          ) : undefined
        }
      >
        <div className="flex flex-wrap items-center gap-2 pt-3 pb-3">
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setWeekStart(addDays(weekStart, -7))}
              aria-label="Vorherige Woche"
            >
              <ChevronLeft aria-hidden />
            </Button>
            <button
              type="button"
              onClick={() => setWeekStart(startOfWeek(new Date()))}
              className={cn(
                'rounded-[var(--radius-sm)] px-2 py-1 text-[length:var(--text-sm)]',
                isCurrentWeek
                  ? 'font-medium text-[var(--color-ink)]'
                  : 'text-[var(--color-brand)] hover:underline',
              )}
            >
              {isCurrentWeek ? 'Diese Woche' : 'Heute'}
            </button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setWeekStart(addDays(weekStart, 7))}
              aria-label="Nächste Woche"
            >
              <ChevronRight aria-hidden />
            </Button>
          </div>
          <span className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
            {weekStart.toLocaleDateString('de-DE')} –{' '}
            {addDays(weekStart, 6).toLocaleDateString('de-DE')}
          </span>
        </div>
      </PageHeader>

      <div className="space-y-4 p-5">
        {permissions.can_write ? <TimerPanel /> : null}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <StatTile label="Diese Woche" value={formatHours(weekSeconds / 3600)} />
          <StatTile
            label="Abrechenbarer Wert"
            value={formatMoney(weekBillable.toFixed(2))}
            tone={weekBillable > 0 ? 'success' : 'default'}
          />
          <StatTile label="Einträge" value={entries.length} />
        </div>

        {entries.length === 0 ? (
          <EmptyState
            icon={<TimerIcon className="size-8" aria-hidden />}
            title="Keine Einträge in dieser Woche"
            description="Starte den Timer oder erfasse einen manuellen Eintrag."
          />
        ) : (
          Array.from({ length: 7 }, (_, index) => addDays(weekStart, index))
            .filter((day) => byDay.has(dayKey(day)))
            .map((day) => {
              const dayEntries = (byDay.get(dayKey(day)) ?? []).sort(
                (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
              );
              const daySeconds = dayEntries.reduce((sum, e) => sum + e.duration_seconds, 0);
              const isToday = dayKey(day) === dayKey(new Date());
              return (
                <GroupSection
                  key={dayKey(day)}
                  color={isToday ? 'var(--color-brand)' : 'var(--color-status-hold)'}
                  title={day.toLocaleDateString('de-DE', {
                    weekday: 'long',
                    day: '2-digit',
                    month: '2-digit',
                  })}
                  meta={
                    <span className="tabular text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
                      Σ {formatHours(daySeconds / 3600)}
                    </span>
                  }
                >
                  <DayTable entries={dayEntries} canEdit={permissions.can_write} />
                </GroupSection>
              );
            })
        )}
      </div>

      <ManualEntryDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Timer panel
// ---------------------------------------------------------------------------

function TimerPanel() {
  const { data } = useTimer();
  const startTimer = useStartTimer();
  const stopTimer = useStopTimer();
  const running = data?.running ?? null;

  const { data: clientsData } = useClients({ archived: false });
  const clients = clientsData?.results ?? [];
  const [clientId, setClientId] = React.useState('');
  const { data: projectsData } = useProjects(clientId ? { client: clientId } : {});
  const projects = (projectsData?.results ?? []).filter((p) => p.status === 'active');
  const { data: serviceData } = useServiceTypes();
  const serviceTypes = serviceData?.results ?? [];

  const [projectId, setProjectId] = React.useState('');
  const [serviceTypeId, setServiceTypeId] = React.useState('');
  const [description, setDescription] = React.useState('');

  const [elapsed, setElapsed] = React.useState(0);
  React.useEffect(() => {
    if (!running) return;
    const startedAt = new Date(running.started_at).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [running]);

  if (running) {
    return (
      <Panel className="border-[var(--color-status-progress)]">
        <PanelBody className="flex flex-wrap items-center gap-4">
          <span className="tabular text-[length:var(--text-3xl)] font-semibold text-[var(--color-status-progress)]">
            {formatDuration(elapsed)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">
              {running.project_name || running.client_name}
            </div>
            <div className="truncate text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
              {running.description || 'Ohne Beschreibung'}
              {running.task_title ? ` · ${running.task_title}` : ''}
            </div>
          </div>
          <Button
            variant="danger"
            onClick={() =>
              stopTimer.mutate(undefined, {
                onSuccess: (entry) =>
                  toast.success(`Gestoppt: ${formatDuration(entry.duration_seconds)}`),
                onError: () => toast.error('Timer konnte nicht gestoppt werden.'),
              })
            }
            loading={stopTimer.isPending}
          >
            <Square className="fill-current" aria-hidden /> Stoppen
          </Button>
        </PanelBody>
      </Panel>
    );
  }

  const start = () => {
    if (!clientId && !projectId) {
      toast.error('Bitte Kunde oder Projekt wählen.');
      return;
    }
    startTimer.mutate(
      {
        client: clientId || undefined,
        project: projectId || undefined,
        service_type: serviceTypeId || undefined,
        description,
      },
      {
        onSuccess: () => {
          setDescription('');
          toast.success('Timer gestartet.');
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Panel>
      <PanelBody className="flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-52">
          <Label htmlFor="timer-client">Kunde</Label>
          <Select
            id="timer-client"
            value={clientId}
            onChange={(event) => {
              setClientId(event.target.value);
              setProjectId('');
            }}
          >
            <option value="">Wählen…</option>
            {clients.map((client) => (
              <option key={client.id} value={client.id}>
                {client.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-full sm:w-52">
          <Label htmlFor="timer-project">Projekt (optional)</Label>
          <Select
            id="timer-project"
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            disabled={!clientId}
          >
            <option value="">Ohne Projekt</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-full sm:w-44">
          <Label htmlFor="timer-service">Leistungsart</Label>
          <Select
            id="timer-service"
            value={serviceTypeId}
            onChange={(event) => setServiceTypeId(event.target.value)}
          >
            <option value="">Keine</option>
            {serviceTypes.map((service) => (
              <option key={service.id} value={service.id}>
                {service.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="min-w-40 flex-1">
          <Label htmlFor="timer-description">Beschreibung</Label>
          <Input
            id="timer-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Woran arbeitest du?"
            onKeyDown={(event) => event.key === 'Enter' && start()}
          />
        </div>
        <Button variant="primary" onClick={start} loading={startTimer.isPending}>
          <Play aria-hidden /> Start
        </Button>
      </PanelBody>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Day table + manual entry
// ---------------------------------------------------------------------------

function DayTable({ entries, canEdit }: { entries: TimeEntry[]; canEdit: boolean }) {
  const deleteEntry = useDeleteTimeEntry();
  return (
    <DataTable>
      <thead>
        <tr>
          <Th className="w-24">Zeit</Th>
          <Th>Kunde / Projekt</Th>
          <Th className="w-[30%]">Beschreibung</Th>
          <Th>Leistungsart</Th>
          <Th className="text-right">Dauer</Th>
          <Th className="text-right">Betrag</Th>
          <Th>Abrechnung</Th>
          {canEdit ? <Th className="w-10" aria-label="Aktionen" /> : null}
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => {
          const locked = ['invoice_draft_created', 'billed'].includes(entry.billing_status);
          return (
            <tr key={entry.id} className="group last:[&>td]:border-b-0">
              <Td className="tabular whitespace-nowrap text-[var(--color-ink-muted)]">
                {new Date(entry.started_at).toLocaleTimeString('de-DE', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </Td>
              <Td>
                <div className="font-medium">{entry.client_name}</div>
                {entry.project_name ? (
                  <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    {entry.project_name}
                  </div>
                ) : null}
              </Td>
              <Td>{entry.description || '—'}</Td>
              <Td className="text-[var(--color-ink-muted)]">{entry.service_type_name ?? '—'}</Td>
              <Td className="tabular text-right font-medium">
                {formatHours(entry.duration_seconds / 3600)}
              </Td>
              <Td className="tabular text-right">
                {entry.billable ? formatMoney(entry.computed_amount) : '—'}
              </Td>
              <Td>
                <BillingBadge status={entry.billing_status} />
              </Td>
              {canEdit ? (
                <Td className="text-right">
                  {!locked ? (
                    <button
                      type="button"
                      onClick={() =>
                        deleteEntry.mutate(entry.id, {
                          onSuccess: () => toast.success('Eintrag gelöscht.'),
                          onError: () => toast.error('Löschen fehlgeschlagen.'),
                        })
                      }
                      aria-label="Eintrag löschen"
                      className="invisible rounded p-1 text-[var(--color-ink-subtle)] group-hover:visible hover:text-[var(--color-danger)]"
                    >
                      <Trash2 className="size-3.5" aria-hidden />
                    </button>
                  ) : null}
                </Td>
              ) : null}
            </tr>
          );
        })}
      </tbody>
    </DataTable>
  );
}

function ManualEntryDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const createEntry = useCreateTimeEntry();
  const { data: clientsData } = useClients({ archived: false });
  const clients = clientsData?.results ?? [];
  const [clientId, setClientId] = React.useState('');
  const { data: projectsData } = useProjects(clientId ? { client: clientId } : {});
  const projects = projectsData?.results ?? [];
  const { data: serviceData } = useServiceTypes();
  const serviceTypes = serviceData?.results ?? [];

  const today = dayKey(new Date());
  const [form, setForm] = React.useState({
    date: today,
    start: '09:00',
    hours: '1',
    projectId: '',
    serviceTypeId: '',
    description: '',
    billable: true,
  });
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((previous) => ({ ...previous, [key]: value }));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!clientId) {
      toast.error('Bitte einen Kunden wählen.');
      return;
    }
    const hours = Number(form.hours.replace(',', '.'));
    if (!Number.isFinite(hours) || hours <= 0) {
      toast.error('Ungültige Dauer.');
      return;
    }
    const startedAt = new Date(`${form.date}T${form.start}:00`);
    createEntry.mutate(
      {
        client: clientId,
        project: form.projectId || null,
        service_type: form.serviceTypeId || null,
        description: form.description,
        started_at: startedAt.toISOString(),
        duration_input_seconds: Math.round(hours * 3600),
        billable: form.billable,
      },
      {
        onSuccess: () => {
          toast.success('Eintrag erfasst.');
          onOpenChange(false);
          setForm((previous) => ({ ...previous, description: '' }));
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Manueller Zeiteintrag">
        <form onSubmit={submit} className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="entry-date">Datum</Label>
              <Input
                id="entry-date"
                type="date"
                value={form.date}
                onChange={(event) => set('date', event.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="entry-start">Start</Label>
              <Input
                id="entry-start"
                type="time"
                value={form.start}
                onChange={(event) => set('start', event.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="entry-hours">Dauer (h)</Label>
              <Input
                id="entry-hours"
                type="text"
                inputMode="decimal"
                value={form.hours}
                onChange={(event) => set('hours', event.target.value)}
                required
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="entry-client" required>
                Kunde
              </Label>
              <Select
                id="entry-client"
                value={clientId}
                onChange={(event) => {
                  setClientId(event.target.value);
                  set('projectId', '');
                }}
                required
              >
                <option value="" disabled>
                  Wählen…
                </option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="entry-project">Projekt</Label>
              <Select
                id="entry-project"
                value={form.projectId}
                onChange={(event) => set('projectId', event.target.value)}
                disabled={!clientId}
              >
                <option value="">Ohne Projekt</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="entry-service">Leistungsart</Label>
              <Select
                id="entry-service"
                value={form.serviceTypeId}
                onChange={(event) => set('serviceTypeId', event.target.value)}
              >
                <option value="">Keine</option>
                {serviceTypes.map((service) => (
                  <option key={service.id} value={service.id}>
                    {service.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex items-end pb-1.5">
              <label className="flex items-center gap-2 text-[length:var(--text-sm)]">
                <input
                  type="checkbox"
                  checked={form.billable}
                  onChange={(event) => set('billable', event.target.checked)}
                  className="size-3.5 accent-[var(--color-brand)]"
                />
                Abrechenbar
              </label>
            </div>
          </div>
          <div>
            <Label htmlFor="entry-description">Beschreibung</Label>
            <Input
              id="entry-description"
              value={form.description}
              onChange={(event) => set('description', event.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button type="submit" variant="primary" loading={createEntry.isPending}>
              Erfassen
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
