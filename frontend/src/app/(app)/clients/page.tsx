'use client';

import {
  Building2,
  Clock3,
  FolderKanban,
  LayoutGrid,
  List,
  Mail,
  Plus,
  Search,
  Trash2,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/app-shell';
import { DeleteClientDialog } from '@/components/clients/delete-client-dialog';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { ClickableRow, DataTable, GroupSection, Td, Th } from '@/components/ui/group-bar';
import { EmptyState } from '@/components/ui/panel';
import { Input, Label } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { StatusTint } from '@/components/ui/status-pill';
import {
  CLIENT_STATUS_LABELS,
  useClients,
  useCreateClient,
  type Client,
  type ClientStatus,
} from '@/lib/api/crm';
import { usePermissions } from '@/lib/session';
import { usePersistedBoolean } from '@/lib/persisted-state';
import { formatHours, formatMoney } from '@/lib/utils';

const STATUS_GROUPS: { status: ClientStatus; color: string }[] = [
  { status: 'active', color: 'var(--color-status-done)' },
  { status: 'prospect', color: 'var(--color-status-todo)' },
  { status: 'paused', color: 'var(--color-status-progress)' },
  { status: 'former', color: 'var(--color-status-hold)' },
];

export default function ClientsPage() {
  const router = useRouter();
  const permissions = usePermissions();
  const [search, setSearch] = React.useState('');
  const [createOpen, setCreateOpen] = React.useState(false);
  const [clientToDelete, setClientToDelete] = React.useState<Client | null>(null);
  const [cardView, setCardView] = usePersistedBoolean('coreflow.clients.card-view', false);

  const { data, isLoading } = useClients({ search: search || undefined, archived: false });
  const clients = React.useMemo(() => data?.results ?? [], [data]);

  const groups = STATUS_GROUPS.map((group) => ({
    ...group,
    clients: clients.filter((client) => client.status === group.status),
  })).filter((group) => group.clients.length > 0);

  return (
    <>
      <PageHeader
        title="Kunden"
        description={`${data?.count ?? '…'} Kunden`}
        actions={
          permissions.can_write ? (
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden /> Neuer Kunde
            </Button>
          ) : undefined
        }
      >
        <div className="flex items-center gap-2 pt-3 pb-3">
          <div className="relative w-full max-w-xs">
            <Search
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-[var(--color-ink-subtle)]"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Suchen…"
              className="pl-8"
              aria-label="Kunden durchsuchen"
            />
          </div>
          <div className="flex overflow-hidden rounded-[var(--radius-sm)] border border-[var(--color-line)]">
            <ViewButton
              active={!cardView}
              label="Tabelle"
              icon={<List aria-hidden />}
              onClick={() => setCardView(false)}
            />
            <ViewButton
              active={cardView}
              label="Karten"
              icon={<LayoutGrid aria-hidden />}
              onClick={() => setCardView(true)}
            />
          </div>
        </div>
      </PageHeader>

      <div className="p-5">
        {isLoading ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : groups.length === 0 ? (
          <EmptyState
            icon={<Building2 className="size-8" aria-hidden />}
            title={search ? 'Keine Treffer' : 'Noch keine Kunden'}
            description={
              search
                ? 'Für diese Suche wurde kein Kunde gefunden.'
                : 'Lege den ersten Kunden an, um Projekte und Zeiten zu erfassen.'
            }
            action={
              permissions.can_write && !search ? (
                <Button variant="primary" onClick={() => setCreateOpen(true)}>
                  <Plus aria-hidden /> Neuer Kunde
                </Button>
              ) : undefined
            }
          />
        ) : (
          groups.map((group) => (
            <GroupSection
              key={group.status}
              color={group.color}
              title={CLIENT_STATUS_LABELS[group.status]}
              count={group.clients.length}
            >
              {cardView ? (
                <div className="grid gap-3 p-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {group.clients.map((client) => (
                    <ClientCard
                      key={client.id}
                      client={client}
                      onOpen={() => router.push(`/clients/${client.id}`)}
                      onDelete={
                        permissions.can_manage_settings
                          ? () => setClientToDelete(client)
                          : undefined
                      }
                    />
                  ))}
                </div>
              ) : (
                <DataTable>
                  <thead>
                    <tr>
                      <Th className="w-[28%]">Kunde</Th>
                      <Th>Nr.</Th>
                      <Th>Ansprechpartner</Th>
                      <Th className="text-right">Offene Stunden</Th>
                      <Th className="text-right">Offener Wert</Th>
                      <Th className="text-center">Projekte</Th>
                      <Th>Letzte Aktivität</Th>
                      {permissions.can_manage_settings ? (
                        <Th className="w-10" aria-label="Aktionen" />
                      ) : null}
                    </tr>
                  </thead>
                  <tbody>
                    {group.clients.map((client) => (
                      <ClientRow
                        key={client.id}
                        client={client}
                        onOpen={() => router.push(`/clients/${client.id}`)}
                        onDelete={
                          permissions.can_manage_settings
                            ? () => setClientToDelete(client)
                            : undefined
                        }
                      />
                    ))}
                  </tbody>
                </DataTable>
              )}
            </GroupSection>
          ))
        )}
      </div>

      <CreateClientDialog open={createOpen} onOpenChange={setCreateOpen} />
      {clientToDelete ? (
        <DeleteClientDialog
          client={clientToDelete}
          open
          onOpenChange={(open) => !open && setClientToDelete(null)}
          onDeleted={() => setClientToDelete(null)}
        />
      ) : null}
    </>
  );
}

function ViewButton({
  active,
  label,
  icon,
  onClick,
}: {
  active: boolean;
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={label}
      className={
        active
          ? 'flex h-8 items-center gap-1.5 bg-[var(--color-brand-subtle)] px-2.5 text-[length:var(--text-xs)] font-medium text-[var(--color-ink)] [&_svg]:size-3.5'
          : 'flex h-8 items-center gap-1.5 px-2.5 text-[length:var(--text-xs)] text-[var(--color-ink-muted)] transition-colors hover:bg-[var(--color-panel-raised)] [&_svg]:size-3.5'
      }
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function ClientCard({
  client,
  onOpen,
  onDelete,
}: {
  client: Client;
  onOpen: () => void;
  onDelete?: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => event.key === 'Enter' && onOpen()}
      className="group min-w-0 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-panel-sunken)] p-4 text-left transition-colors hover:border-[var(--color-line-strong)] hover:bg-[var(--color-panel-raised)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-brand)]"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--color-brand-subtle)] text-[var(--color-brand)]">
          <Building2 className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold text-[var(--color-ink)] group-hover:text-[var(--color-brand)]">
            {client.name}
          </div>
          <div className="truncate text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            {[client.client_number, client.industry].filter(Boolean).join(' · ') || 'Ohne Zusatz'}
          </div>
        </div>
        {onDelete ? (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onDelete();
            }}
            aria-label={`Kunde „${client.name}“ löschen`}
            className="rounded p-1 text-[var(--color-ink-subtle)] opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[var(--color-danger)]/10 hover:text-[var(--color-danger)] focus:opacity-100"
          >
            <Trash2 className="size-3.5" aria-hidden />
          </button>
        ) : null}
      </div>

      <div className="mt-4 min-h-9">
        {client.primary_contact ? (
          <>
            <div className="truncate text-[length:var(--text-sm)]">
              {client.primary_contact.full_name}
            </div>
            <div className="flex items-center gap-1.5 truncate text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
              <Mail className="size-3 shrink-0" aria-hidden />
              {client.primary_contact.email || 'Keine E-Mail'}
            </div>
          </>
        ) : (
          <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            Kein Ansprechpartner
          </span>
        )}
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-[var(--color-line)] pt-3">
        <div>
          <dt className="flex items-center gap-1 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            <Clock3 className="size-3" aria-hidden /> Offen
          </dt>
          <dd className="tabular mt-0.5 text-[length:var(--text-sm)] font-medium">
            {client.stats.open_seconds > 0 ? formatHours(client.stats.open_seconds / 3600) : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">Wert</dt>
          <dd className="tabular mt-0.5 truncate text-[length:var(--text-sm)] font-medium text-[var(--color-success)]">
            {client.stats.open_seconds > 0
              ? formatMoney(client.stats.open_amount, client.currency)
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-1 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            <FolderKanban className="size-3" aria-hidden /> Projekte
          </dt>
          <dd className="tabular mt-0.5 text-[length:var(--text-sm)] font-medium">
            {client.stats.active_projects || '—'}
          </dd>
        </div>
      </dl>
      <div className="mt-3 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
        Letzte Aktivität:{' '}
        {client.stats.last_activity_at
          ? new Date(client.stats.last_activity_at).toLocaleDateString('de-DE')
          : '—'}
      </div>
    </div>
  );
}

function ClientRow({
  client,
  onOpen,
  onDelete,
}: {
  client: Client;
  onOpen: () => void;
  onDelete?: () => void;
}) {
  return (
    <ClickableRow
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter') onOpen();
      }}
      tabIndex={0}
    >
      <Td>
        <div className="font-medium">{client.name}</div>
        {client.industry ? (
          <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            {client.industry}
          </div>
        ) : null}
      </Td>
      <Td className="tabular text-[var(--color-ink-muted)]">{client.client_number}</Td>
      <Td>
        {client.primary_contact ? (
          <div>
            <div>{client.primary_contact.full_name}</div>
            <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
              {client.primary_contact.email}
            </div>
          </div>
        ) : (
          <span className="text-[var(--color-ink-subtle)]">—</span>
        )}
      </Td>
      <Td className="tabular text-right">
        {client.stats.open_seconds > 0 ? formatHours(client.stats.open_seconds / 3600) : '—'}
      </Td>
      <Td className="tabular text-right">
        {client.stats.open_seconds > 0 ? (
          <span className="font-medium text-[var(--color-success)]">
            {formatMoney(client.stats.open_amount, client.currency)}
          </span>
        ) : (
          '—'
        )}
      </Td>
      <Td className="text-center">
        {client.stats.active_projects > 0 ? (
          <StatusTint tone="todo">{client.stats.active_projects}</StatusTint>
        ) : (
          <span className="text-[var(--color-ink-subtle)]">—</span>
        )}
      </Td>
      <Td className="text-[var(--color-ink-muted)]">
        {client.stats.last_activity_at
          ? new Date(client.stats.last_activity_at).toLocaleDateString('de-DE')
          : '—'}
      </Td>
      {onDelete ? (
        <Td className="text-right" onClick={(event) => event.stopPropagation()}>
          <button
            type="button"
            onClick={onDelete}
            aria-label={`Kunde „${client.name}“ löschen`}
            className="rounded p-1 text-[var(--color-ink-subtle)] hover:bg-[var(--color-danger)]/10 hover:text-[var(--color-danger)]"
          >
            <Trash2 className="size-3.5" aria-hidden />
          </button>
        </Td>
      ) : null}
    </ClickableRow>
  );
}

function CreateClientDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const createClient = useCreateClient();
  const [name, setName] = React.useState('');
  const [status, setStatus] = React.useState<ClientStatus>('active');
  const [email, setEmail] = React.useState('');
  const [rate, setRate] = React.useState('');

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    createClient.mutate(
      {
        name: name.trim(),
        status,
        email: email.trim(),
        default_hourly_rate: rate ? rate : null,
      },
      {
        onSuccess: (client) => {
          toast.success(`Kunde „${client.name}“ angelegt.`);
          onOpenChange(false);
          setName('');
          setEmail('');
          setRate('');
          router.push(`/clients/${client.id}`);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Neuer Kunde" description="Kundennummer wird automatisch vergeben.">
        <form onSubmit={submit} className="space-y-3">
          <div>
            <Label htmlFor="client-name" required>
              Firmenname
            </Label>
            <Input
              id="client-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="client-status">Status</Label>
              <Select
                id="client-status"
                value={status}
                onChange={(event) => setStatus(event.target.value as ClientStatus)}
              >
                {Object.entries(CLIENT_STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="client-rate">Stundensatz (€)</Label>
              <Input
                id="client-rate"
                type="number"
                step="0.01"
                min="0"
                value={rate}
                placeholder="Workspace-Standard"
                onChange={(event) => setRate(event.target.value)}
              />
            </div>
          </div>
          <div>
            <Label htmlFor="client-email">E-Mail</Label>
            <Input
              id="client-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button type="submit" variant="primary" loading={createClient.isPending}>
              Anlegen
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
