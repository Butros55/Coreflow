'use client';

import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Circle, Database, PlugZap, XCircle } from 'lucide-react';

import { PageHeader } from '@/components/layout/app-shell';
import { Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import { systemApi } from '@/lib/api/system';
import { useSession } from '@/lib/session';
import { formatMoney } from '@/lib/utils';

/**
 * Übersicht.
 *
 * Phase 0 deliberately shows only what genuinely exists: the real workspace
 * profile and live system/integration status from /readyz. Revenue, hours and
 * pipeline tiles arrive with the phases that create that data — a placeholder
 * KPI on a finance screen is worse than an absent one.
 */
export default function DashboardPage() {
  const { data: session } = useSession();
  const workspace = session?.workspace;

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

  const integrations = readiness.data?.checks.integrations;

  return (
    <>
      <PageHeader
        title={`Willkommen, ${session?.user.first_name || session?.user.email.split('@')[0] || ''}`}
        description={workspace?.name}
      />

      <div className="p-5">
        <div className="grid gap-4 lg:grid-cols-3">
          <Panel className="lg:col-span-2">
            <PanelHeader>
              <PanelTitle>Unternehmensprofil</PanelTitle>
            </PanelHeader>
            <PanelBody>
              {workspace ? (
                <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                  <Field label="Firma" value={workspace.legal_name || workspace.name} />
                  <Field label="Rechtsform" value={workspace.legal_form} />
                  <Field label="Steuernummer" value={workspace.tax_number} />
                  <Field label="USt-IdNr." value={workspace.vat_id} />
                  <Field
                    label="Standardstundensatz"
                    value={formatMoney(workspace.default_hourly_rate, workspace.default_currency)}
                  />
                  <Field
                    label="Zahlungsziel"
                    value={`${workspace.default_payment_term_days} Tage`}
                  />
                  <Field
                    label="Kleinunternehmer (§19 UStG)"
                    value={workspace.small_business ? 'Ja' : 'Nein'}
                  />
                  <Field
                    label="Zeitrundung"
                    value={
                      workspace.time_rounding_increment_minutes === 0
                        ? 'Keine'
                        : `${workspace.time_rounding_increment_minutes} Min (${workspace.time_rounding_strategy})`
                    }
                  />
                </dl>
              ) : (
                <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
                  Kein Workspace zugeordnet.
                </p>
              )}
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader>
              <PanelTitle>Systemstatus</PanelTitle>
            </PanelHeader>
            <PanelBody className="space-y-3">
              <StatusRow
                icon={<Database className="size-4" aria-hidden />}
                label="Datenbank"
                ok={readiness.data?.checks.database.status === 'ok'}
                loading={readiness.isLoading}
                detail={
                  readiness.data?.checks.database.latency_ms !== undefined
                    ? `${readiness.data.checks.database.latency_ms} ms`
                    : undefined
                }
              />
              <StatusRow
                icon={<Database className="size-4" aria-hidden />}
                label="Cache"
                ok={readiness.data?.checks.cache.status === 'ok'}
                loading={readiness.isLoading}
                detail={
                  readiness.data?.checks.cache.latency_ms !== undefined
                    ? `${readiness.data.checks.cache.latency_ms} ms`
                    : undefined
                }
              />

              <div className="border-t border-[var(--color-line)] pt-3">
                <div className="mb-2 flex items-center gap-1.5 text-[length:var(--text-xs)] font-medium text-[var(--color-ink-muted)]">
                  <PlugZap className="size-3.5" aria-hidden />
                  Integrationen
                </div>
                <div className="space-y-2">
                  <IntegrationRow name="Lexware Office" state={integrations?.lexware} />
                  <IntegrationRow name="Clockodo" state={integrations?.clockodo} />
                </div>
                <p className="mt-2.5 text-[length:var(--text-2xs)] leading-relaxed text-[var(--color-ink-subtle)]">
                  Beide Integrationen sind optional. Die Zeiterfassung und alle Kern­funktionen
                  arbeiten vollständig ohne sie.
                </p>
              </div>

              {version.data ? (
                <div className="border-t border-[var(--color-line)] pt-3 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                  v{version.data.version} · {version.data.environment} · {version.data.time_zone}
                </div>
              ) : null}
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="min-w-0">
      <dt className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">{label}</dt>
      <dd className="truncate text-[length:var(--text-sm)] text-[var(--color-ink)]">
        {value || '—'}
      </dd>
    </div>
  );
}

function StatusRow({
  icon,
  label,
  ok,
  loading,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  ok: boolean;
  loading: boolean;
  detail?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[var(--color-ink-subtle)]">{icon}</span>
      <span className="flex-1 text-[length:var(--text-sm)]">{label}</span>
      {detail ? (
        <span className="tabular text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
          {detail}
        </span>
      ) : null}
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
