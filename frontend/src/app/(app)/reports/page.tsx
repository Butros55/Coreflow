'use client';

import {
  BadgeEuro,
  BarChart3,
  Building2,
  Clock3,
  FolderKanban,
  HandCoins,
  Hourglass,
  Receipt,
  TrendingUp,
} from 'lucide-react';
import Link from 'next/link';
import { Bar, BarChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { PageHeader } from '@/components/layout/app-shell';
import { DataTable, Td, Th } from '@/components/ui/group-bar';
import {
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelTitle,
  StatTile,
} from '@/components/ui/panel';
import { useBusinessReport, type BusinessReport } from '@/lib/api/finance';
import { formatHours, formatMoney } from '@/lib/utils';

const TOOLTIP_STYLE = {
  background: 'var(--color-panel)',
  border: '1px solid var(--color-line)',
  borderRadius: 10,
  fontSize: 12,
  boxShadow: 'var(--shadow-popover)',
} as const;

function monthLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('de-DE', { month: 'short' });
}

/**
 * Berichte: das interne Zahlenwerk.
 *
 * Alles kommt aus einem Endpoint (/finance/report), damit sich Kacheln und
 * Diagramme nie widersprechen. Aufbau: Lage (KPIs) → Verlauf (Monatsreihen) →
 * Struktur (Kunden, Leistungsarten) → Wirtschaftlichkeit (Projekte).
 */
export default function ReportsPage() {
  const { data: report, isLoading } = useBusinessReport();

  return (
    <>
      <PageHeader
        title="Berichte"
        description={
          report
            ? `Internes Reporting ${report.year} · Basis: Rechnungen, Zeiten, Projekte und Kunden`
            : 'Internes Reporting'
        }
      />

      <div className="space-y-4 p-5">
        {isLoading || !report ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : (
          <ReportBody report={report} />
        )}
      </div>
    </>
  );
}

function ReportBody({ report }: { report: BusinessReport }) {
  const { kpis } = report;
  const hasAnyData =
    Number(kpis.revenue_ytd) > 0 ||
    report.months.some((month) => month.seconds > 0) ||
    report.projects.length > 0;

  if (!hasAnyData) {
    return (
      <EmptyState
        icon={<BarChart3 className="size-8" aria-hidden />}
        title="Noch keine Auswertungsdaten"
        description="Sobald Zeiten erfasst und Rechnungen gestellt sind, entsteht hier das interne Reporting mit Umsatz, Auslastung und Projekt-Wirtschaftlichkeit."
      />
    );
  }

  return (
    <>
      {/* Lage: die acht Kennzahlen für den schnellen Blick. */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          icon={<TrendingUp />}
          label="Umsatz (Jahr)"
          value={formatMoney(kpis.revenue_ytd)}
          hint={`Ø ${formatMoney(kpis.avg_monthly_revenue)} je aktivem Monat`}
        />
        <StatTile
          icon={<BadgeEuro />}
          label="Effektiver Stundensatz"
          value={kpis.effective_hourly_rate ? formatMoney(kpis.effective_hourly_rate) : '—'}
          hint="Umsatz ÷ abgerechnete Stunden"
        />
        <StatTile
          icon={<Clock3 />}
          label="Abrechenbare Quote"
          value={
            kpis.billable_share_90d !== null
              ? `${Math.round(kpis.billable_share_90d * 100)} %`
              : '—'
          }
          hint="Anteil abrechenbarer Zeit, 90 Tage"
          tone={
            kpis.billable_share_90d !== null && kpis.billable_share_90d < 0.5
              ? 'warning'
              : 'default'
          }
        />
        <StatTile
          icon={<HandCoins />}
          label="Ø Zahlungsdauer"
          value={kpis.avg_days_to_pay !== null ? `${kpis.avg_days_to_pay} Tage` : '—'}
          hint="Rechnungsdatum → Zahlung, 12 Monate"
        />
        <StatTile
          icon={<Receipt />}
          label="Offene Forderungen"
          value={formatMoney(kpis.open_receivables)}
          tone={Number(kpis.overdue_receivables) > 0 ? 'danger' : 'default'}
          hint={
            Number(kpis.overdue_receivables) > 0
              ? `davon überfällig: ${formatMoney(kpis.overdue_receivables)}`
              : 'Nichts überfällig'
          }
        />
        <StatTile
          icon={<Hourglass />}
          label="Pipeline"
          value={formatMoney(kpis.unbilled_value)}
          hint={`${formatHours(kpis.unbilled_seconds / 3600)} nicht abgerechnet · Entwürfe ${formatMoney(kpis.draft_total)}`}
          tone={Number(kpis.unbilled_value) > 0 ? 'warning' : 'default'}
        />
        <StatTile
          icon={<Building2 />}
          label="Aktive Kunden"
          value={kpis.active_clients_90d}
          hint={`von ${kpis.total_clients} gesamt · letzte 90 Tage`}
        />
        <StatTile
          icon={<FolderKanban />}
          label="Aktive Projekte"
          value={kpis.active_projects}
          hint="mit Status „Aktiv“"
        />
      </div>

      {/* Verlauf: Umsatz und Stunden getrennt — eine Achse pro Diagramm. */}
      <div className="grid gap-4 lg:grid-cols-2">
        <RevenueChart report={report} />
        <HoursChart report={report} />
      </div>

      {/* Struktur: wer bringt den Umsatz, womit wird er erwirtschaftet. */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ClientsPanel report={report} />
        </div>
        <div className="space-y-4">
          <ConcentrationPanel report={report} />
          <ServicesPanel report={report} />
        </div>
      </div>

      <ProjectsPanel report={report} />
    </>
  );
}

function RevenueChart({ report }: { report: BusinessReport }) {
  const data = report.months.map((month) => ({
    label: monthLabel(month.month),
    invoiced: Number(month.invoiced_net),
    paid: Number(month.paid_net),
  }));
  return (
    <Panel>
      <PanelHeader>
        <div>
          <PanelTitle>Umsatz je Monat</PanelTitle>
          <p className="mt-0.5 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            Fakturierte Netto-Beträge, letzte 12 Monate
          </p>
        </div>
      </PanelHeader>
      <PanelBody>
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, left: -8, right: 0 }}>
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
                tickFormatter={(value: number) =>
                  value >= 1000 ? `${Math.round(value / 1000)}k` : String(value)
                }
              />
              <Tooltip
                cursor={{ fill: 'var(--color-panel-raised)' }}
                contentStyle={TOOLTIP_STYLE}
                formatter={(value, name) => [
                  formatMoney(Number(value).toFixed(2)),
                  name === 'invoiced' ? 'Fakturiert' : 'Davon bezahlt',
                ]}
              />
              <Bar
                dataKey="invoiced"
                fill="var(--color-brand)"
                radius={[4, 4, 0, 0]}
                maxBarSize={20}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </PanelBody>
    </Panel>
  );
}

function HoursChart({ report }: { report: BusinessReport }) {
  const data = report.months.map((month) => ({
    label: monthLabel(month.month),
    billable: Math.round((month.billable_seconds / 3600) * 100) / 100,
    nonBillable: Math.round(((month.seconds - month.billable_seconds) / 3600) * 100) / 100,
  }));
  return (
    <Panel>
      <PanelHeader>
        <div>
          <PanelTitle>Erfasste Stunden je Monat</PanelTitle>
          <p className="mt-0.5 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            Abrechenbar vs. nicht abrechenbar
          </p>
        </div>
      </PanelHeader>
      <PanelBody>
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, left: -12, right: 0 }}>
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
                tickFormatter={(value: number) => `${value}h`}
              />
              <Tooltip
                cursor={{ fill: 'var(--color-panel-raised)' }}
                contentStyle={TOOLTIP_STYLE}
                formatter={(value, name) => [
                  formatHours(Number(value)),
                  name === 'billable' ? 'Abrechenbar' : 'Nicht abrechenbar',
                ]}
              />
              <Legend
                formatter={(value: string) => (
                  <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-muted)]">
                    {value === 'billable' ? 'Abrechenbar' : 'Nicht abrechenbar'}
                  </span>
                )}
                iconType="circle"
                iconSize={8}
              />
              <Bar dataKey="billable" stackId="hours" fill="var(--color-brand)" maxBarSize={20} />
              <Bar
                dataKey="nonBillable"
                stackId="hours"
                fill="var(--color-line-strong)"
                radius={[4, 4, 0, 0]}
                maxBarSize={20}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </PanelBody>
    </Panel>
  );
}

function ClientsPanel({ report }: { report: BusinessReport }) {
  if (report.clients.length === 0) {
    return (
      <Panel>
        <PanelHeader>
          <PanelTitle>Umsatz nach Kunde</PanelTitle>
        </PanelHeader>
        <PanelBody>
          <p className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            Noch keine fakturierten Umsätze in {report.year}.
          </p>
        </PanelBody>
      </Panel>
    );
  }
  return (
    <Panel>
      <PanelHeader>
        <div>
          <PanelTitle>Umsatz nach Kunde</PanelTitle>
          <p className="mt-0.5 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            Fakturiert {report.year} · effektiver Satz aus abgerechneten Stunden
          </p>
        </div>
      </PanelHeader>
      <DataTable>
        <thead>
          <tr>
            <Th className="w-[40%]">Kunde</Th>
            <Th className="text-right">Umsatz</Th>
            <Th className="text-right">Anteil</Th>
            <Th className="text-right">Stunden</Th>
            <Th className="text-right">Eff. Satz</Th>
            <Th className="text-right">Offen</Th>
          </tr>
        </thead>
        <tbody>
          {report.clients.map((client) => (
            <tr key={client.id} className="last:[&>td]:border-b-0">
              <Td>
                <div className="font-medium">{client.name}</div>
                <div className="mt-1 h-1 w-full max-w-40 overflow-hidden rounded-full bg-[var(--color-panel-sunken)]">
                  <div
                    className="h-full rounded-full bg-[var(--color-brand)]"
                    style={{ width: `${Math.round(client.share * 100)}%` }}
                  />
                </div>
              </Td>
              <Td className="tabular text-right font-medium">{formatMoney(client.invoiced_net)}</Td>
              <Td className="tabular text-right text-[var(--color-ink-muted)]">
                {Math.round(client.share * 100)} %
              </Td>
              <Td className="tabular text-right text-[var(--color-ink-muted)]">
                {client.seconds > 0 ? formatHours(client.seconds / 3600) : '—'}
              </Td>
              <Td className="tabular text-right text-[var(--color-ink-muted)]">
                {client.effective_rate ? formatMoney(client.effective_rate) : '—'}
              </Td>
              <Td className="tabular text-right">
                {Number(client.open_gross) > 0 ? (
                  <span className="font-medium text-[var(--color-warning)]">
                    {formatMoney(client.open_gross)}
                  </span>
                ) : (
                  '—'
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </Panel>
  );
}

function ConcentrationPanel({ report }: { report: BusinessReport }) {
  const concentration = report.concentration;
  if (!concentration) return null;
  const percent = Math.round(concentration.share * 100);
  const risky = concentration.share >= 0.5;
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Kundenkonzentration</PanelTitle>
      </PanelHeader>
      <PanelBody className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <span className="min-w-0 truncate text-[length:var(--text-sm)]">
            {concentration.client_name}
          </span>
          <span
            className="tabular text-[length:var(--text-2xl)] font-semibold"
            style={{ color: risky ? 'var(--color-warning)' : 'var(--color-ink)' }}
          >
            {percent} %
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-panel-sunken)]">
          <div
            className="h-full rounded-full"
            style={{
              width: `${percent}%`,
              backgroundColor: risky ? 'var(--color-warning)' : 'var(--color-brand)',
            }}
          />
        </div>
        <p className="text-[length:var(--text-2xs)] leading-relaxed text-[var(--color-ink-subtle)]">
          Anteil des größten Kunden am Jahresumsatz.
          {risky
            ? ' Über 50 % — ein Ausfall dieses Kunden träfe das Geschäft hart.'
            : ' Unter 50 % — die Umsatzbasis ist breit genug verteilt.'}
        </p>
      </PanelBody>
    </Panel>
  );
}

function ServicesPanel({ report }: { report: BusinessReport }) {
  const total = report.services.reduce((sum, service) => sum + Number(service.value), 0);
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Leistungsarten</PanelTitle>
      </PanelHeader>
      <PanelBody>
        {report.services.length === 0 ? (
          <p className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            Noch keine abgerechneten Leistungen.
          </p>
        ) : (
          <ul className="space-y-2.5">
            {report.services.map((service) => {
              const pct = total > 0 ? (Number(service.value) / total) * 100 : 0;
              return (
                <li key={service.name}>
                  <div className="mb-0.5 flex items-baseline justify-between gap-2 text-[length:var(--text-sm)]">
                    <span className="min-w-0 truncate">{service.name}</span>
                    <span className="tabular shrink-0 font-medium">
                      {formatMoney(service.value)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--color-panel-sunken)]">
                      <div
                        className="h-full rounded-full bg-[var(--color-brand)]"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="tabular shrink-0 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                      {formatHours(service.seconds / 3600)}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </PanelBody>
    </Panel>
  );
}

function ProjectsPanel({ report }: { report: BusinessReport }) {
  if (report.projects.length === 0) return null;
  return (
    <Panel>
      <PanelHeader>
        <div>
          <PanelTitle>Projekt-Wirtschaftlichkeit</PanelTitle>
          <p className="mt-0.5 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            Aktive Projekte: erfasste Zeit, Budgetauslastung und offener Wert
          </p>
        </div>
      </PanelHeader>
      <DataTable>
        <thead>
          <tr>
            <Th className="w-[30%]">Projekt</Th>
            <Th>Budget</Th>
            <Th className="text-right">Stunden</Th>
            <Th className="text-right">Zeitwert</Th>
            <Th className="text-right">Fakturiert</Th>
            <Th className="text-right">Nicht abgerechnet</Th>
          </tr>
        </thead>
        <tbody>
          {report.projects.map((project) => {
            const overBudget = project.budget_used_share !== null && project.budget_used_share > 1;
            return (
              <tr key={project.id} className="last:[&>td]:border-b-0">
                <Td>
                  <Link
                    href={`/projects/${project.id}`}
                    className="font-medium text-[var(--color-brand)] hover:underline"
                  >
                    {project.name}
                  </Link>
                  <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    {project.client_name}
                  </div>
                </Td>
                <Td>
                  {project.budget_used_share !== null ? (
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-[var(--color-panel-sunken)]">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.min(100, Math.round(project.budget_used_share * 100))}%`,
                            backgroundColor: overBudget
                              ? 'var(--color-danger)'
                              : project.budget_used_share > 0.8
                                ? 'var(--color-warning)'
                                : 'var(--color-brand)',
                          }}
                        />
                      </div>
                      <span
                        className="tabular text-[length:var(--text-2xs)]"
                        style={{
                          color: overBudget ? 'var(--color-danger)' : 'var(--color-ink-subtle)',
                        }}
                      >
                        {Math.round(project.budget_used_share * 100)} %
                      </span>
                    </div>
                  ) : (
                    <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                      Kein Budget
                    </span>
                  )}
                </Td>
                <Td className="tabular text-right">
                  {formatHours(project.seconds / 3600)}
                  {project.budget_hours ? (
                    <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                      {' '}
                      / {formatHours(project.budget_hours)}
                    </span>
                  ) : null}
                </Td>
                <Td className="tabular text-right">{formatMoney(project.value)}</Td>
                <Td className="tabular text-right">{formatMoney(project.invoiced_net)}</Td>
                <Td className="tabular text-right">
                  {Number(project.unbilled_value) > 0 ? (
                    <span className="font-medium text-[var(--color-warning)]">
                      {formatMoney(project.unbilled_value)}
                    </span>
                  ) : (
                    '—'
                  )}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </DataTable>
    </Panel>
  );
}
