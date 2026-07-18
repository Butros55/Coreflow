'use client';

import {
  AlertTriangle,
  ArrowDownUp,
  CheckCircle2,
  Info,
  Plug,
  RefreshCw,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import {
  useIntegrationStatus,
  useResolveConflict,
  useSyncConflicts,
  useTestConnection,
  useTriggerSync,
  type IntegrationStatus,
} from '@/lib/api/settings';

const PROVIDER_META = {
  lexware: {
    name: 'Lexware Office',
    role: 'Rechnungen, Kontakte, Zahlungen (führendes System)',
    note: 'Rechnungen werden als Entwurf erstellt. Die rechtsgültige Finalisierung erfolgt in Lexware — die API kann einen Entwurf nachträglich nicht finalisieren.',
    envHint: 'LEXWARE_ENABLED=true und LEXWARE_API_KEY in der .env setzen.',
  },
  clockodo: {
    name: 'Clockodo',
    role: 'Optionale Zeiterfassung — Coreflow funktioniert vollständig ohne',
    note: 'Webhooks können nicht per API registriert werden: im Clockodo-Menü einrichten und das zugesandte Secret hier hinterlegen.',
    envHint:
      'CLOCKODO_ENABLED=true, CLOCKODO_API_USER, CLOCKODO_API_KEY und CLOCKODO_EXTERNAL_APP_EMAIL setzen.',
  },
} as const;

export function IntegrationsTab() {
  const { data } = useIntegrationStatus();

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        {(['lexware', 'clockodo'] as const).map((provider) =>
          data ? (
            <ProviderCard key={provider} provider={provider} status={data[provider]} />
          ) : (
            <Panel key={provider}>
              <PanelBody>
                <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
              </PanelBody>
            </Panel>
          ),
        )}
      </div>
      <ConflictsPanel />
    </div>
  );
}

function ProviderCard({
  provider,
  status,
}: {
  provider: 'lexware' | 'clockodo';
  status: IntegrationStatus;
}) {
  const meta = PROVIDER_META[provider];
  const test = useTestConnection();
  const sync = useTriggerSync();

  const stateLabel = !status.enabled
    ? { tone: 'hold' as const, text: 'Deaktiviert', icon: XCircle }
    : !status.configured
      ? { tone: 'stuck' as const, text: 'Nicht konfiguriert', icon: AlertTriangle }
      : status.connected
        ? { tone: 'done' as const, text: 'Verbunden', icon: CheckCircle2 }
        : { tone: 'progress' as const, text: 'Konfiguriert', icon: Plug };

  const StateIcon = stateLabel.icon;

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          <span className="inline-flex items-center gap-2">
            <StateIcon
              className="size-4"
              style={{ color: `var(--color-status-${stateLabel.tone})` }}
              aria-hidden
            />
            {meta.name}
          </span>
        </PanelTitle>
        <StatusTint tone={stateLabel.tone}>{stateLabel.text}</StatusTint>
      </PanelHeader>
      <PanelBody className="space-y-3">
        <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">{meta.role}</p>

        {status.connected && status.profile ? (
          <dl className="grid grid-cols-2 gap-2 rounded-[var(--radius-sm)] bg-[var(--color-panel-sunken)] p-2.5 text-[length:var(--text-xs)]">
            <div>
              <dt className="text-[var(--color-ink-subtle)]">Firma</dt>
              <dd>{status.profile.company_name || '—'}</dd>
            </div>
            {status.profile.tax_type ? (
              <div>
                <dt className="text-[var(--color-ink-subtle)]">Steuerart</dt>
                <dd>{status.profile.tax_type}</dd>
              </div>
            ) : null}
            <div>
              <dt className="text-[var(--color-ink-subtle)]">Verknüpfte Objekte</dt>
              <dd className="tabular">{status.linked_objects}</dd>
            </div>
            <div>
              <dt className="text-[var(--color-ink-subtle)]">Zuletzt geprüft</dt>
              <dd>
                {status.profile.fetched_at
                  ? new Date(status.profile.fetched_at).toLocaleString('de-DE', {
                      dateStyle: 'short',
                      timeStyle: 'short',
                    })
                  : '—'}
              </dd>
            </div>
          </dl>
        ) : null}

        {status.last_failure_at ? (
          <div className="rounded-[var(--radius-sm)] border border-[var(--color-danger)] bg-[var(--color-danger-soft)] p-2 text-[length:var(--text-2xs)] text-[var(--color-danger)]">
            Letzter Fehler: {status.last_failure_summary || 'unbekannt'}
          </div>
        ) : null}

        {!status.enabled || !status.configured ? (
          <div className="flex gap-2 rounded-[var(--radius-sm)] border border-[var(--color-line)] bg-[var(--color-panel-sunken)] p-2.5 text-[length:var(--text-2xs)] text-[var(--color-ink-muted)]">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <p>{meta.envHint}</p>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                loading={test.isPending && test.variables === provider}
                onClick={() =>
                  test.mutate(provider, {
                    onSuccess: (result) =>
                      toast.success(`Verbunden mit ${result.company_name || meta.name}.`),
                    onError: (error) => toast.error(error.message),
                  })
                }
              >
                <RefreshCw aria-hidden /> Verbindung testen
              </Button>
              {status.connected ? (
                <Button
                  variant="secondary"
                  size="sm"
                  loading={sync.isPending && sync.variables === provider}
                  onClick={() =>
                    sync.mutate(provider, {
                      onSuccess: () =>
                        toast.success(
                          'Synchronisierung gestartet — Ergebnisse erscheinen hier in Kürze.',
                        ),
                      onError: (error) => toast.error(error.message),
                    })
                  }
                >
                  <ArrowDownUp aria-hidden /> Jetzt synchronisieren
                </Button>
              ) : null}
              {status.webhook_configured ? (
                <StatusTint tone="done">Webhook konfiguriert</StatusTint>
              ) : (
                <StatusTint tone="hold">Kein Webhook</StatusTint>
              )}
            </div>
            {provider === 'clockodo' && status.webhook_url ? (
              <div className="space-y-1 rounded-[var(--radius-sm)] border border-[var(--color-line)] bg-[var(--color-panel-sunken)] p-2.5 text-[length:var(--text-2xs)]">
                <p className="text-[var(--color-ink-muted)]">
                  Webhook-URL (im Clockodo-Menü eintragen):
                </p>
                <code className="block break-all text-[var(--color-ink)]">
                  {status.webhook_url}
                </code>
                {status.webhook_handshake_secret ? (
                  <>
                    <p className="pt-1 text-[var(--color-ink-muted)]">
                      Empfangenes Handshake-Secret (zurück in Clockodo einfügen):
                    </p>
                    <code className="block break-all text-[var(--color-ink)]">
                      {status.webhook_handshake_secret}
                    </code>
                  </>
                ) : null}
              </div>
            ) : null}
          </>
        )}

        <p className="border-t border-[var(--color-line)] pt-2.5 text-[length:var(--text-2xs)] leading-relaxed text-[var(--color-ink-subtle)]">
          {meta.note}
        </p>
      </PanelBody>
    </Panel>
  );
}

function ConflictsPanel() {
  const { data } = useSyncConflicts();
  const resolve = useResolveConflict();
  const conflicts = data?.results ?? [];

  if (conflicts.length === 0) return null;

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          <span className="inline-flex items-center gap-2">
            <AlertTriangle className="size-4 text-[var(--color-warning)]" aria-hidden />
            Offene Synchronisationskonflikte ({conflicts.length})
          </span>
        </PanelTitle>
      </PanelHeader>
      <PanelBody className="space-y-3">
        {conflicts.map((conflict) => (
          <div
            key={conflict.id}
            className="rounded-[var(--radius-md)] border border-[var(--color-line)] p-3"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-[length:var(--text-sm)] font-medium">
                {conflict.provider} · {conflict.resource_type}
              </span>
              <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                {conflict.reason}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[length:var(--text-2xs)]">
              <pre className="overflow-x-auto rounded bg-[var(--color-panel-sunken)] p-2">
                Lokal: {JSON.stringify(conflict.local_snapshot, null, 1)}
              </pre>
              <pre className="overflow-x-auto rounded bg-[var(--color-panel-sunken)] p-2">
                Remote: {JSON.stringify(conflict.remote_snapshot, null, 1)}
              </pre>
            </div>
            <div className="mt-2 flex gap-2">
              {(['local', 'remote', 'ignore'] as const).map((choice) => (
                <Button
                  key={choice}
                  variant="secondary"
                  size="xs"
                  onClick={() =>
                    resolve.mutate(
                      { id: conflict.id, resolution: choice },
                      { onError: (error) => toast.error(error.message) },
                    )
                  }
                >
                  {choice === 'local'
                    ? 'Lokal behalten'
                    : choice === 'remote'
                      ? 'Remote übernehmen'
                      : 'Ignorieren'}
                </Button>
              ))}
            </div>
          </div>
        ))}
      </PanelBody>
    </Panel>
  );
}
