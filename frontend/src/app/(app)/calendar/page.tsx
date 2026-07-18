'use client';

import { ChevronLeft, ChevronRight, Download, Plus } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/app-shell';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Input, Label, Textarea } from '@/components/ui/input';
import { Panel } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import { StatusTint, type StatusTone } from '@/components/ui/status-pill';
import { useClients } from '@/lib/api/crm';
import {
  APPOINTMENT_STATUS_LABELS,
  appointmentsIcsUrl,
  useAppointments,
  useSaveAppointment,
  type Appointment,
  type AppointmentStatus,
} from '@/lib/api/scheduling';
import { usePermissions } from '@/lib/session';
import { cn } from '@/lib/utils';

const STATUS_TONES: Record<AppointmentStatus, StatusTone> = {
  planned: 'todo',
  confirmed: 'progress',
  done: 'done',
  cancelled: 'stuck',
};

function monthStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}
function addMonths(date: Date, n: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + n, 1);
}
function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/** Six-week grid (Mon-first) covering the visible month. */
function monthGrid(month: Date): Date[] {
  const first = monthStart(month);
  const offset = (first.getDay() + 6) % 7; // Monday = 0
  const start = new Date(first);
  start.setDate(first.getDate() - offset);
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}

export default function CalendarPage() {
  const permissions = usePermissions();
  const [month, setMonth] = React.useState(() => monthStart(new Date()));
  const [createOpen, setCreateOpen] = React.useState(false);
  const [createDate, setCreateDate] = React.useState<string | null>(null);

  const gridStart = monthGrid(month)[0]!;
  const gridEnd = new Date(gridStart);
  gridEnd.setDate(gridStart.getDate() + 42);

  const { data } = useAppointments({
    from_date: gridStart.toISOString(),
    to_date: gridEnd.toISOString(),
  });
  const appointments = React.useMemo(() => data?.results ?? [], [data]);

  const byDay = React.useMemo(() => {
    const map = new Map<string, Appointment[]>();
    for (const appt of appointments) {
      const key = dayKey(new Date(appt.starts_at));
      map.set(key, [...(map.get(key) ?? []), appt]);
    }
    return map;
  }, [appointments]);

  const days = monthGrid(month);
  const todayKey = dayKey(new Date());
  const monthName = month.toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });

  const openCreate = (date?: Date) => {
    setCreateDate(date ? dayKey(date) : null);
    setCreateOpen(true);
  };

  return (
    <>
      <PageHeader
        title="Kalender"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" asChild>
              <a href={appointmentsIcsUrl()} download>
                <Download aria-hidden /> ICS-Export
              </a>
            </Button>
            {permissions.can_write ? (
              <Button variant="primary" onClick={() => openCreate()}>
                <Plus aria-hidden /> Termin
              </Button>
            ) : null}
          </div>
        }
      >
        <div className="flex items-center gap-2 pt-3 pb-3">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setMonth(addMonths(month, -1))}
            aria-label="Vorheriger Monat"
          >
            <ChevronLeft aria-hidden />
          </Button>
          <button
            type="button"
            onClick={() => setMonth(monthStart(new Date()))}
            className="min-w-40 text-center text-[length:var(--text-base)] font-medium capitalize"
          >
            {monthName}
          </button>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setMonth(addMonths(month, 1))}
            aria-label="Nächster Monat"
          >
            <ChevronRight aria-hidden />
          </Button>
        </div>
      </PageHeader>

      <div className="p-5">
        <Panel>
          <div className="grid grid-cols-7 border-b border-[var(--color-line)]">
            {['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'].map((d) => (
              <div
                key={d}
                className="px-2 py-1.5 text-[length:var(--text-2xs)] font-semibold tracking-wider text-[var(--color-ink-subtle)] uppercase"
              >
                {d}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7">
            {days.map((day) => {
              const key = dayKey(day);
              const inMonth = day.getMonth() === month.getMonth();
              const isToday = key === todayKey;
              const dayAppts = (byDay.get(key) ?? []).sort(
                (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
              );
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => permissions.can_write && openCreate(day)}
                  className={cn(
                    'min-h-24 border-r border-b border-[var(--color-line-subtle)] p-1.5 text-left align-top transition-colors last:border-r-0 hover:bg-[var(--color-panel-raised)]',
                    !inMonth && 'bg-[var(--color-panel-sunken)] opacity-60',
                  )}
                >
                  <div
                    className={cn(
                      'mb-1 inline-flex size-5 items-center justify-center rounded-full text-[length:var(--text-xs)]',
                      isToday
                        ? 'bg-[var(--color-brand)] font-semibold text-white'
                        : 'text-[var(--color-ink-muted)]',
                    )}
                  >
                    {day.getDate()}
                  </div>
                  <div className="space-y-1">
                    {dayAppts.slice(0, 3).map((appt) => (
                      <div
                        key={appt.id}
                        className="truncate rounded-[var(--radius-xs)] px-1.5 py-0.5 text-[length:var(--text-2xs)]"
                        style={{
                          backgroundColor: `var(--color-status-${STATUS_TONES[appt.status]}-soft)`,
                          color: `var(--color-status-${STATUS_TONES[appt.status]})`,
                        }}
                        title={`${new Date(appt.starts_at).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })} ${appt.title}`}
                      >
                        {new Date(appt.starts_at).toLocaleTimeString('de-DE', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}{' '}
                        {appt.title}
                      </div>
                    ))}
                    {dayAppts.length > 3 ? (
                      <div className="px-1.5 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                        +{dayAppts.length - 3} weitere
                      </div>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
        </Panel>

        <UpcomingList appointments={appointments} />
      </div>

      <AppointmentDialog open={createOpen} onOpenChange={setCreateOpen} defaultDate={createDate} />
    </>
  );
}

function UpcomingList({ appointments }: { appointments: Appointment[] }) {
  const now = new Date();
  const upcoming = appointments
    .filter((a) => new Date(a.ends_at) >= now && a.status !== 'cancelled')
    .sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime())
    .slice(0, 6);
  if (upcoming.length === 0) return null;
  return (
    <div className="mt-4">
      <h2 className="mb-2 text-[length:var(--text-sm)] font-semibold text-[var(--color-ink-muted)]">
        Nächste Termine
      </h2>
      <div className="space-y-2">
        {upcoming.map((appt) => (
          <Panel key={appt.id} className="flex items-center gap-3 p-3">
            <div className="w-14 shrink-0 text-center">
              <div className="text-[length:var(--text-lg)] leading-none font-semibold">
                {new Date(appt.starts_at).getDate()}
              </div>
              <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)] uppercase">
                {new Date(appt.starts_at).toLocaleDateString('de-DE', { month: 'short' })}
              </div>
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-medium">{appt.title}</div>
              <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                {new Date(appt.starts_at).toLocaleTimeString('de-DE', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
                {appt.client_name ? ` · ${appt.client_name}` : ''}
                {appt.location ? ` · ${appt.location}` : ''}
              </div>
            </div>
            <StatusTint tone={STATUS_TONES[appt.status]}>
              {APPOINTMENT_STATUS_LABELS[appt.status]}
            </StatusTint>
          </Panel>
        ))}
      </div>
    </div>
  );
}

function AppointmentDialog({
  open,
  onOpenChange,
  defaultDate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultDate: string | null;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Remount on each open (and clicked day) so the form starts fresh —
          the idiomatic "reset state on prop change" without an effect. */}
      <AppointmentForm
        key={`${open}-${defaultDate}`}
        defaultDate={defaultDate}
        onDone={() => onOpenChange(false)}
      />
    </Dialog>
  );
}

function AppointmentForm({
  defaultDate,
  onDone,
}: {
  defaultDate: string | null;
  onDone: () => void;
}) {
  const save = useSaveAppointment();
  const { data: clientsData } = useClients({ archived: false });
  const clients = clientsData?.results ?? [];

  const [form, setForm] = React.useState({
    title: '',
    date: defaultDate ?? dayKey(new Date()),
    start: '10:00',
    end: '11:00',
    clientId: '',
    location: '',
    description: '',
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.title.trim()) return;
    const starts = new Date(`${form.date}T${form.start}:00`);
    const ends = new Date(`${form.date}T${form.end}:00`);
    save.mutate(
      {
        title: form.title.trim(),
        starts_at: starts.toISOString(),
        ends_at: ends.toISOString(),
        client: form.clientId || null,
        location: form.location,
        description: form.description,
      },
      {
        onSuccess: () => {
          toast.success('Termin gespeichert.');
          onDone();
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <DialogContent title="Neuer Termin">
      <form onSubmit={submit} className="space-y-3">
        <div>
          <Label htmlFor="appt-title" required>
            Titel
          </Label>
          <Input
            id="appt-title"
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            autoFocus
            required
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label htmlFor="appt-date">Datum</Label>
            <Input
              id="appt-date"
              type="date"
              value={form.date}
              onChange={(e) => set('date', e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="appt-start">Beginn</Label>
            <Input
              id="appt-start"
              type="time"
              value={form.start}
              onChange={(e) => set('start', e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="appt-end">Ende</Label>
            <Input
              id="appt-end"
              type="time"
              value={form.end}
              onChange={(e) => set('end', e.target.value)}
              required
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="appt-client">Kunde</Label>
            <Select
              id="appt-client"
              value={form.clientId}
              onChange={(e) => set('clientId', e.target.value)}
            >
              <option value="">Ohne Kunde</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="appt-location">Ort / Link</Label>
            <Input
              id="appt-location"
              value={form.location}
              onChange={(e) => set('location', e.target.value)}
              placeholder="Videocall, vor Ort…"
            />
          </div>
        </div>
        <div>
          <Label htmlFor="appt-desc">Beschreibung</Label>
          <Textarea
            id="appt-desc"
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onDone}>
            Abbrechen
          </Button>
          <Button type="submit" variant="primary" loading={save.isPending}>
            Speichern
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}
