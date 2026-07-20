'use client';

import { Search, ShieldCheck } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { DataTable, Td, Th } from '@/components/ui/group-bar';
import { Input, Label } from '@/components/ui/input';
import { EmptyState, Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import { useAuditLog, type AuditLogEntry } from '@/lib/api/audit';

const ACTION_LABELS: Record<string, string> = {
  'auth.login': 'Anmeldung',
  'auth.login_failed': 'Anmeldung fehlgeschlagen',
  'auth.logout': 'Abmeldung',
  'auth.password_changed': 'Passwort geändert',
  'workspace.created': 'Workspace angelegt',
  'workspace.updated': 'Workspace geändert',
  'member.updated': 'Teamrolle geändert',
  'member.removed': 'Teammitglied entfernt',
  'invoice.sent': 'Rechnung übertragen',
  'invoice.cancelled': 'Rechnung storniert',
  'invoice.remote_deleted': 'Lexware-Entwurf gelöscht',
  'invoice.remote_voided': 'Rechnung in Lexware storniert',
  'integration.connection_tested': 'Verbindung geprüft',
  'integration.sync_triggered': 'Synchronisierung gestartet',
  'integration.conflict_resolved': 'Sync-Konflikt gelöst',
  'privacy.client_exported': 'Kundendaten exportiert',
  'privacy.client_erased': 'Kundendaten anonymisiert',
  'privacy.client_deleted': 'Kundendaten gelöscht',
  'time.exported': 'Zeiterfassung exportiert',
};

const ACTION_GROUPS = [
  { value: '', label: 'Alle Bereiche' },
  { value: 'auth.', label: 'Anmeldung & Sicherheit' },
  { value: 'workspace.', label: 'Workspace' },
  { value: 'member.', label: 'Team' },
  { value: 'invoice.', label: 'Rechnungen' },
  { value: 'integration.', label: 'Integrationen' },
  { value: 'privacy.', label: 'Datenschutz' },
  { value: 'time.', label: 'Zeiterfassung' },
] as const;

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

function targetLabel(entry: AuditLogEntry): string {
  if (!entry.target_type && !entry.target_id) return '—';
  const type = entry.target_type.split('.').at(-1) || entry.target_type;
  const shortId = entry.target_id.length > 14 ? `${entry.target_id.slice(0, 8)}…` : entry.target_id;
  return [type, shortId].filter(Boolean).join(' · ');
}

export function AuditLogTab() {
  const [action, setAction] = React.useState('');
  const [search, setSearch] = React.useState('');
  const [page, setPage] = React.useState(1);
  const { data, isLoading } = useAuditLog({
    action: action || undefined,
    page,
  });
  const rows = React.useMemo(() => {
    const needle = search.trim().toLocaleLowerCase('de-DE');
    if (!needle) return data?.results ?? [];
    return (data?.results ?? []).filter((entry) =>
      [
        actionLabel(entry.action),
        entry.action,
        entry.actor_email,
        entry.summary,
        entry.target_type,
        entry.target_id,
      ].some((value) => value.toLocaleLowerCase('de-DE').includes(needle)),
    );
  }, [data?.results, search]);

  const changeAction = (value: string) => {
    setAction(value);
    setPage(1);
  };

  return (
    <Panel>
      <PanelHeader className="items-start">
        <div>
          <PanelTitle>Audit-Protokoll</PanelTitle>
          <p className="mt-1 text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
            Unveränderliche Sicherheits- und Geschäftsereignisse dieses Workspaces.
          </p>
        </div>
        <ShieldCheck className="size-5 text-[var(--color-brand)]" aria-hidden />
      </PanelHeader>
      <PanelBody className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-full sm:w-64">
            <Label htmlFor="audit-search">Aktuelle Seite durchsuchen</Label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-[var(--color-ink-subtle)]"
                aria-hidden
              />
              <Input
                id="audit-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Aktion, Person, Ziel…"
                className="pl-8"
              />
            </div>
          </div>
          <div className="w-full sm:w-56">
            <Label htmlFor="audit-area">Bereich</Label>
            <Select
              id="audit-area"
              value={action}
              onChange={(event) => changeAction(event.target.value)}
            >
              {ACTION_GROUPS.map((group) => (
                <option key={group.value} value={group.value}>
                  {group.label}
                </option>
              ))}
            </Select>
          </div>
          <span className="flex-1" />
          <span className="tabular pb-1 text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
            {data ? `${data.count} Ereignisse` : '…'}
          </span>
        </div>

        {isLoading ? (
          <p className="py-5 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<ShieldCheck className="size-8" aria-hidden />}
            title={search ? 'Keine Treffer auf dieser Seite' : 'Keine Ereignisse'}
            description={
              search
                ? 'Passe den Suchbegriff oder Bereich an.'
                : 'Für diesen Bereich wurden noch keine Audit-Ereignisse aufgezeichnet.'
            }
          />
        ) : (
          <div className="overflow-x-auto rounded-[var(--radius-sm)] border border-[var(--color-line)]">
            <DataTable>
              <thead>
                <tr>
                  <Th className="w-36">Zeitpunkt</Th>
                  <Th>Aktion</Th>
                  <Th>Ausgeführt von</Th>
                  <Th>Zusammenfassung</Th>
                  <Th>Ziel</Th>
                  <Th>IP-Adresse</Th>
                  <Th className="w-20">Details</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr key={entry.id} className="last:[&>td]:border-b-0">
                    <Td className="tabular whitespace-nowrap text-[var(--color-ink-muted)]">
                      {new Date(entry.created_at).toLocaleString('de-DE', {
                        dateStyle: 'short',
                        timeStyle: 'short',
                      })}
                    </Td>
                    <Td>
                      <div className="font-medium">{actionLabel(entry.action)}</div>
                      <div className="font-mono text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                        {entry.action}
                      </div>
                    </Td>
                    <Td className="text-[var(--color-ink-muted)]">
                      {entry.actor_email || 'System / unbekannt'}
                    </Td>
                    <Td>{entry.summary || '—'}</Td>
                    <Td className="font-mono text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
                      {targetLabel(entry)}
                    </Td>
                    <Td className="tabular text-[var(--color-ink-muted)]">
                      {entry.ip_address || '—'}
                    </Td>
                    <Td>
                      {Object.keys(entry.metadata).length > 0 ? (
                        <details className="relative">
                          <summary className="cursor-pointer text-[length:var(--text-xs)] text-[var(--color-brand)]">
                            Anzeigen
                          </summary>
                          <pre className="mt-2 max-w-80 overflow-auto rounded-[var(--radius-xs)] bg-[var(--color-panel-sunken)] p-2 text-[length:var(--text-2xs)] whitespace-pre-wrap text-[var(--color-ink-muted)]">
                            {JSON.stringify(entry.metadata, null, 2)}
                          </pre>
                        </details>
                      ) : (
                        '—'
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </div>
        )}

        {data && data.num_pages > 1 ? (
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button
              variant="ghost"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Zurück
            </Button>
            <span className="tabular text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
              Seite {page} von {data.num_pages}
            </span>
            <Button
              variant="ghost"
              size="sm"
              disabled={page >= data.num_pages}
              onClick={() => setPage((current) => current + 1)}
            >
              Weiter
            </Button>
          </div>
        ) : null}
      </PanelBody>
    </Panel>
  );
}
