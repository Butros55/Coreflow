'use client';

import { ArrowLeft, Mail, Phone, Plus, Star } from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/app-shell';
import { DetailErrorState } from '@/components/ui/detail-error';
import { api } from '@/lib/api/client';
import { BillingBadge } from '@/components/time/billing-badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { ClickableRow, DataTable, Td, Th } from '@/components/ui/group-bar';
import { Input, Label, Textarea } from '@/components/ui/input';
import {
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelTitle,
  StatTile,
} from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import { StatusTint } from '@/components/ui/status-pill';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  CLIENT_STATUS_LABELS,
  useClient,
  useClientActivities,
  useClientContacts,
  useClientNotes,
  useCreateNote,
  useSaveContact,
  type ClientContact,
  type ClientNote,
} from '@/lib/api/crm';
import { PROJECT_STATUS_LABELS, useProjects } from '@/lib/api/projects';
import { useTimeEntries } from '@/lib/api/time';
import { usePermissions } from '@/lib/session';
import { formatHours, formatMoney } from '@/lib/utils';

const NOTE_TYPE_LABELS: Record<ClientNote['note_type'], string> = {
  note: 'Notiz',
  call: 'Telefonat',
  meeting: 'Termin',
  email: 'E-Mail',
};

export default function ClientDetailPage() {
  const params = useParams<{ id: string }>();
  const clientId = params.id;
  const { data: client, isLoading, error } = useClient(clientId);
  const permissions = usePermissions();

  if (isLoading) {
    return (
      <div className="p-5 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</div>
    );
  }
  if (error || !client) {
    return (
      <DetailErrorState
        error={error}
        entityLabel="Kunde"
        backHref="/clients"
        backLabel="Alle Kunden"
      />
    );
  }

  const statusTone = { active: 'done', prospect: 'todo', paused: 'progress', former: 'hold' }[
    client.status
  ] as 'done' | 'todo' | 'progress' | 'hold';

  return (
    <>
      <PageHeader
        title={client.name}
        description={[client.client_number, client.legal_form, client.industry]
          .filter(Boolean)
          .join(' · ')}
        actions={
          <div className="flex items-center gap-2">
            <StatusTint tone={statusTone}>{CLIENT_STATUS_LABELS[client.status]}</StatusTint>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/clients">
                <ArrowLeft aria-hidden /> Alle Kunden
              </Link>
            </Button>
          </div>
        }
      >
        <Tabs defaultValue="overview">
          <TabsList className="border-b-0 pt-2">
            <TabsTrigger value="overview">Übersicht</TabsTrigger>
            <TabsTrigger value="projects">Projekte</TabsTrigger>
            <TabsTrigger value="contacts">Kontakte</TabsTrigger>
            <TabsTrigger value="time">Zeiten</TabsTrigger>
            <TabsTrigger value="notes">Notizen</TabsTrigger>
            <TabsTrigger value="activity">Aktivität</TabsTrigger>
          </TabsList>

          <div className="-mx-5 border-t border-[var(--color-line)] bg-[var(--color-canvas)] px-5 pt-5 pb-5">
            <TabsContent value="overview">
              <OverviewTab client={client} />
            </TabsContent>
            <TabsContent value="projects">
              <ProjectsTab clientId={clientId} />
            </TabsContent>
            <TabsContent value="contacts">
              <ContactsTab clientId={clientId} canEdit={permissions.can_write} />
            </TabsContent>
            <TabsContent value="time">
              <TimeTab clientId={clientId} />
            </TabsContent>
            <TabsContent value="notes">
              <NotesTab clientId={clientId} canEdit={permissions.can_write} />
            </TabsContent>
            <TabsContent value="activity">
              <ActivityTab clientId={clientId} />
            </TabsContent>
          </div>
        </Tabs>
      </PageHeader>
    </>
  );
}

function OverviewTab({ client }: { client: NonNullable<ReturnType<typeof useClient>['data']> }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Nicht abgerechnete Stunden"
          value={
            client.stats.open_seconds > 0 ? formatHours(client.stats.open_seconds / 3600) : '0,00 h'
          }
        />
        <StatTile
          label="Wert offener Stunden"
          value={formatMoney(client.stats.open_amount, client.currency)}
          tone={Number(client.stats.open_amount) > 0 ? 'success' : 'default'}
        />
        <StatTile label="Laufende Projekte" value={client.stats.active_projects} />
        <StatTile
          label="Letzte Aktivität"
          value={
            client.stats.last_activity_at
              ? new Date(client.stats.last_activity_at).toLocaleDateString('de-DE')
              : '—'
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHeader>
            <PanelTitle>Stammdaten</PanelTitle>
          </PanelHeader>
          <PanelBody>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[length:var(--text-sm)]">
              <Info
                label="Stundensatz"
                value={
                  client.default_hourly_rate
                    ? formatMoney(client.default_hourly_rate)
                    : 'Workspace-Standard'
                }
              />
              <Info
                label="Zahlungsziel"
                value={client.payment_term_days ? `${client.payment_term_days} Tage` : '—'}
              />
              <Info label="USt-IdNr." value={client.vat_id || '—'} />
              <Info label="Steuernummer" value={client.tax_number || '—'} />
              <Info
                label="Kunde seit"
                value={
                  client.customer_since
                    ? new Date(client.customer_since).toLocaleDateString('de-DE')
                    : '—'
                }
              />
              <Info label="Akquise" value={client.acquisition_source || '—'} />
              <Info
                label="Rechnungsadresse"
                value={
                  client.billing_street
                    ? `${client.billing_street}, ${client.billing_zip} ${client.billing_city}`
                    : '—'
                }
              />
              <Info label="Website" value={client.website || '—'} />
            </dl>
            {client.tags.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {client.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-[var(--radius-xs)] bg-[var(--color-brand-subtle)] px-2 py-0.5 text-[length:var(--text-2xs)] text-[var(--color-brand)]"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>Hauptansprechpartner</PanelTitle>
          </PanelHeader>
          <PanelBody>
            {client.primary_contact ? (
              <div className="space-y-2 text-[length:var(--text-sm)]">
                <div className="text-[length:var(--text-base)] font-medium">
                  {client.primary_contact.full_name}
                </div>
                {client.primary_contact.email ? (
                  <div className="flex items-center gap-2 text-[var(--color-ink-muted)]">
                    <Mail className="size-3.5" aria-hidden />
                    <a href={`mailto:${client.primary_contact.email}`} className="hover:underline">
                      {client.primary_contact.email}
                    </a>
                  </div>
                ) : null}
                {client.primary_contact.phone ? (
                  <div className="flex items-center gap-2 text-[var(--color-ink-muted)]">
                    <Phone className="size-3.5" aria-hidden />
                    {client.primary_contact.phone}
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
                Kein Hauptansprechpartner hinterlegt.
              </p>
            )}
            {client.notes ? (
              <div className="mt-4 border-t border-[var(--color-line)] pt-3">
                <div className="mb-1 text-[length:var(--text-xs)] font-medium text-[var(--color-ink-muted)]">
                  Interne Notizen
                </div>
                <p className="text-[length:var(--text-sm)] whitespace-pre-wrap">{client.notes}</p>
              </div>
            ) : null}
          </PanelBody>
        </Panel>
      </div>
      <PrivacyPanel client={client} />
    </div>
  );
}

function PrivacyPanel({ client }: { client: NonNullable<ReturnType<typeof useClient>['data']> }) {
  const permissions = usePermissions();
  const router = useRouter();
  const [eraseOpen, setEraseOpen] = React.useState(false);
  const [confirmName, setConfirmName] = React.useState('');
  const [busy, setBusy] = React.useState<'export' | 'erase' | null>(null);

  if (!permissions.can_manage_settings) return null;

  const downloadExport = async () => {
    setBusy('export');
    try {
      const bundle = await api.get<Record<string, unknown>>(`/clients/${client.id}/export/`);
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `kunde-${client.client_number || client.id}-export.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.success('Datenexport erstellt.');
    } catch {
      toast.error('Export fehlgeschlagen.');
    } finally {
      setBusy(null);
    }
  };

  const erase = async () => {
    setBusy('erase');
    try {
      const result = await api.post<{ mode: 'deleted' | 'anonymized' }>(
        `/clients/${client.id}/erase/`,
        { confirm: confirmName },
      );
      if (result.mode === 'deleted') {
        toast.success('Kunde vollständig gelöscht.');
        router.push('/clients');
      } else {
        toast.success('Personenbezogene Daten anonymisiert. Rechnungsdaten bleiben erhalten.');
        setEraseOpen(false);
        window.location.reload();
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Löschen fehlgeschlagen.');
      setBusy(null);
    }
  };

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Datenschutz (DSGVO)</PanelTitle>
      </PanelHeader>
      <PanelBody className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            loading={busy === 'export'}
            onClick={downloadExport}
          >
            Datenauskunft exportieren (Art. 15)
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-[var(--color-danger)]"
            onClick={() => setEraseOpen(true)}
          >
            Kunden löschen / anonymisieren (Art. 17)
          </Button>
        </div>
        <p className="text-[length:var(--text-2xs)] leading-relaxed text-[var(--color-ink-subtle)]">
          Rechnungen und abgerechnete Zeiten unterliegen der Aufbewahrungspflicht (§ 147 AO / § 257
          HGB, bis zu 10 Jahre) und werden bei einer Löschung nicht entfernt — stattdessen werden
          alle personenbezogenen Felder anonymisiert. Ohne Geschäftsunterlagen wird der Kunde
          vollständig gelöscht.
        </p>
      </PanelBody>

      <Dialog open={eraseOpen} onOpenChange={setEraseOpen}>
        <DialogContent title="Kunden löschen / anonymisieren">
          <div className="space-y-3">
            <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
              Kontakte, Notizen und Aktivitäten werden gelöscht, personenbezogene Felder geleert.
              Diese Aktion kann nicht rückgängig gemacht werden.
            </p>
            <div>
              <Label htmlFor="erase-confirm" required>
                Zur Bestätigung den Namen „{client.name}“ eingeben
              </Label>
              <Input
                id="erase-confirm"
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="ghost" onClick={() => setEraseOpen(false)}>
                Abbrechen
              </Button>
              <Button
                type="button"
                variant="primary"
                className="bg-[var(--color-danger)] hover:bg-[var(--color-danger)]/85"
                loading={busy === 'erase'}
                disabled={confirmName !== client.name}
                onClick={erase}
              >
                Unwiderruflich löschen
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">{label}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  );
}

function ProjectsTab({ clientId }: { clientId: string }) {
  const router = useRouter();
  const { data } = useProjects({ client: clientId });
  const projects = data?.results ?? [];

  if (projects.length === 0) {
    return (
      <EmptyState
        title="Keine Projekte"
        description="Für diesen Kunden existiert noch kein Projekt."
      />
    );
  }
  return (
    <Panel>
      <DataTable>
        <thead>
          <tr>
            <Th>Projekt</Th>
            <Th>Status</Th>
            <Th className="text-right">Offene Aufgaben</Th>
            <Th className="text-right">Erfasste Zeit</Th>
            <Th>Zieldatum</Th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <ClickableRow key={project.id} onClick={() => router.push(`/projects/${project.id}`)}>
              <Td>
                <span
                  className="mr-2 inline-block size-2 rounded-full align-middle"
                  style={{ backgroundColor: project.color || 'var(--color-brand)' }}
                  aria-hidden
                />
                <span className="font-medium">{project.name}</span>
              </Td>
              <Td>
                <StatusTint tone={project.status === 'active' ? 'done' : 'hold'}>
                  {PROJECT_STATUS_LABELS[project.status]}
                </StatusTint>
              </Td>
              <Td className="tabular text-right">{project.stats.open_tasks}</Td>
              <Td className="tabular text-right">
                {formatHours(project.stats.logged_seconds / 3600)}
              </Td>
              <Td>
                {project.target_date
                  ? new Date(project.target_date).toLocaleDateString('de-DE')
                  : '—'}
              </Td>
            </ClickableRow>
          ))}
        </tbody>
      </DataTable>
    </Panel>
  );
}

function ContactsTab({ clientId, canEdit }: { clientId: string; canEdit: boolean }) {
  const { data } = useClientContacts(clientId);
  const saveContact = useSaveContact(clientId);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const contacts = data?.results ?? [];

  return (
    <div className="space-y-3">
      {canEdit ? (
        <div className="flex justify-end">
          <Button variant="secondary" size="sm" onClick={() => setDialogOpen(true)}>
            <Plus aria-hidden /> Ansprechpartner
          </Button>
        </div>
      ) : null}
      {contacts.length === 0 ? (
        <EmptyState title="Keine Kontakte" description="Noch kein Ansprechpartner hinterlegt." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {contacts.map((contact) => (
            <Panel key={contact.id} className="p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div className="font-medium">{contact.full_name}</div>
                {contact.is_primary ? (
                  <Star
                    className="size-4 shrink-0 fill-[var(--color-warning)] text-[var(--color-warning)]"
                    aria-label="Hauptansprechpartner"
                  />
                ) : canEdit ? (
                  <button
                    type="button"
                    className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)] hover:text-[var(--color-ink)] hover:underline"
                    onClick={() =>
                      saveContact.mutate(
                        { id: contact.id, is_primary: true },
                        { onError: () => toast.error('Konnte nicht gesetzt werden.') },
                      )
                    }
                  >
                    Als Hauptkontakt
                  </button>
                ) : null}
              </div>
              {contact.position ? (
                <div className="text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
                  {contact.position}
                </div>
              ) : null}
              <div className="mt-2 space-y-1 text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
                {contact.email ? (
                  <div className="flex items-center gap-1.5">
                    <Mail className="size-3" aria-hidden />
                    <a href={`mailto:${contact.email}`} className="truncate hover:underline">
                      {contact.email}
                    </a>
                  </div>
                ) : null}
                {contact.phone || contact.mobile ? (
                  <div className="flex items-center gap-1.5">
                    <Phone className="size-3" aria-hidden />
                    {contact.phone || contact.mobile}
                  </div>
                ) : null}
              </div>
            </Panel>
          ))}
        </div>
      )}
      <ContactDialog open={dialogOpen} onOpenChange={setDialogOpen} clientId={clientId} />
    </div>
  );
}

function ContactDialog({
  open,
  onOpenChange,
  clientId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clientId: string;
}) {
  const saveContact = useSaveContact(clientId);
  const [form, setForm] = React.useState({
    first_name: '',
    last_name: '',
    position: '',
    email: '',
    phone: '',
    is_primary: false,
  });
  const set = (key: keyof typeof form, value: string | boolean) =>
    setForm((previous) => ({ ...previous, [key]: value }));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.first_name.trim() || !form.last_name.trim()) return;
    saveContact.mutate(form as Partial<ClientContact>, {
      onSuccess: () => {
        onOpenChange(false);
        setForm({
          first_name: '',
          last_name: '',
          position: '',
          email: '',
          phone: '',
          is_primary: false,
        });
      },
      onError: (error) => toast.error(error.message),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Neuer Ansprechpartner">
        <form onSubmit={submit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="contact-first" required>
                Vorname
              </Label>
              <Input
                id="contact-first"
                value={form.first_name}
                onChange={(e) => set('first_name', e.target.value)}
                required
                autoFocus
              />
            </div>
            <div>
              <Label htmlFor="contact-last" required>
                Nachname
              </Label>
              <Input
                id="contact-last"
                value={form.last_name}
                onChange={(e) => set('last_name', e.target.value)}
                required
              />
            </div>
          </div>
          <div>
            <Label htmlFor="contact-position">Position</Label>
            <Input
              id="contact-position"
              value={form.position}
              onChange={(e) => set('position', e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="contact-email">E-Mail</Label>
              <Input
                id="contact-email"
                type="email"
                value={form.email}
                onChange={(e) => set('email', e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="contact-phone">Telefon</Label>
              <Input
                id="contact-phone"
                value={form.phone}
                onChange={(e) => set('phone', e.target.value)}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-[length:var(--text-sm)]">
            <input
              type="checkbox"
              checked={form.is_primary}
              onChange={(e) => set('is_primary', e.target.checked)}
              className="size-3.5 accent-[var(--color-brand)]"
            />
            Hauptansprechpartner
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button type="submit" variant="primary" loading={saveContact.isPending}>
              Speichern
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TimeTab({ clientId }: { clientId: string }) {
  const { data } = useTimeEntries({ client: clientId });
  const entries = data?.results ?? [];

  if (entries.length === 0) {
    return (
      <EmptyState
        title="Keine Zeiten"
        description="Für diesen Kunden wurde noch keine Zeit erfasst."
      />
    );
  }
  return (
    <Panel>
      <DataTable>
        <thead>
          <tr>
            <Th>Datum</Th>
            <Th>Beschreibung</Th>
            <Th>Projekt</Th>
            <Th className="text-right">Dauer</Th>
            <Th className="text-right">Betrag</Th>
            <Th>Abrechnung</Th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id} className="last:[&>td]:border-b-0">
              <Td className="whitespace-nowrap text-[var(--color-ink-muted)]">
                {new Date(entry.started_at).toLocaleDateString('de-DE')}
              </Td>
              <Td>{entry.description || '—'}</Td>
              <Td className="text-[var(--color-ink-muted)]">{entry.project_name ?? '—'}</Td>
              <Td className="tabular text-right">{formatHours(entry.duration_seconds / 3600)}</Td>
              <Td className="tabular text-right">
                {entry.billable ? formatMoney(entry.computed_amount) : '—'}
              </Td>
              <Td>
                <BillingBadge status={entry.billing_status} />
              </Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </Panel>
  );
}

function NotesTab({ clientId, canEdit }: { clientId: string; canEdit: boolean }) {
  const { data } = useClientNotes(clientId);
  const createNote = useCreateNote(clientId);
  const [content, setContent] = React.useState('');
  const [noteType, setNoteType] = React.useState<ClientNote['note_type']>('note');
  const notes = data?.results ?? [];

  const submit = () => {
    const trimmed = content.trim();
    if (!trimmed) return;
    createNote.mutate(
      { content: trimmed, note_type: noteType },
      { onSuccess: () => setContent(''), onError: (error) => toast.error(error.message) },
    );
  };

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {canEdit ? (
        <Panel className="p-4">
          <Textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="Neue Notiz…"
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <Select
              value={noteType}
              onChange={(event) => setNoteType(event.target.value as ClientNote['note_type'])}
              className="w-36"
              aria-label="Notiztyp"
            >
              {Object.entries(NOTE_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
            <Button
              variant="primary"
              size="sm"
              onClick={submit}
              disabled={!content.trim()}
              loading={createNote.isPending}
            >
              Speichern
            </Button>
          </div>
        </Panel>
      ) : null}
      {notes.length === 0 ? (
        <EmptyState title="Keine Notizen" />
      ) : (
        notes.map((note) => (
          <Panel key={note.id} className="p-4">
            <div className="mb-1.5 flex items-center gap-2 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
              <StatusTint tone="neutral">{NOTE_TYPE_LABELS[note.note_type]}</StatusTint>
              <span>
                {note.author?.full_name} ·{' '}
                {new Date(note.created_at).toLocaleString('de-DE', {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                })}
              </span>
            </div>
            <p className="text-[length:var(--text-sm)] whitespace-pre-wrap">{note.content}</p>
          </Panel>
        ))
      )}
    </div>
  );
}

function ActivityTab({ clientId }: { clientId: string }) {
  const { data } = useClientActivities(clientId);
  const activities = data?.results ?? [];

  if (activities.length === 0) {
    return <EmptyState title="Keine Aktivitäten" />;
  }
  return (
    <div className="mx-auto max-w-2xl">
      <ol className="relative space-y-4 border-l border-[var(--color-line)] pl-5">
        {activities.map((activity) => (
          <li key={activity.id} className="relative">
            <span
              className="absolute top-1 -left-[26px] size-2.5 rounded-full border-2 border-[var(--color-canvas)] bg-[var(--color-brand)]"
              aria-hidden
            />
            <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
              {new Date(activity.occurred_at).toLocaleString('de-DE', {
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
              {' · '}
              {activity.event_type_display}
            </div>
            <div className="text-[length:var(--text-sm)]">{activity.description}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}
