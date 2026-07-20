'use client';

import { AlertTriangle, Info, PiggyBank } from 'lucide-react';
import * as React from 'react';

import { PageHeader } from '@/components/layout/app-shell';
import { DataTable, Td } from '@/components/ui/group-bar';
import { Input, Label } from '@/components/ui/input';
import { Panel, PanelBody, PanelHeader, PanelTitle, StatTile } from '@/components/ui/panel';
import {
  useFinanceDashboard,
  useReserve,
  useReserveScenario,
  type ReserveForecast,
  type TraceStep,
} from '@/lib/api/finance';
import { formatHours, formatMoney } from '@/lib/utils';

export default function FinancePage() {
  const { data: dashboard, isLoading } = useFinanceDashboard();
  const { data: reserve } = useReserve();

  const kpis = dashboard?.kpis;

  return (
    <>
      <PageHeader title="Finanzen" description={`Geschäftsjahr ${dashboard?.year ?? ''}`}>
        <div className="pb-4" />
      </PageHeader>

      <div className="space-y-4 p-5">
        {isLoading ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                label="Umsatz (Jahr)"
                value={formatMoney(kpis?.revenue_ytd)}
                hint={`Monat: ${formatMoney(kpis?.revenue_month)} · Quartal: ${formatMoney(kpis?.revenue_quarter)}`}
              />
              <StatTile
                label="Offene Forderungen"
                value={formatMoney(kpis?.open_receivables)}
                tone={Number(kpis?.open_receivables ?? 0) > 0 ? 'warning' : 'default'}
                hint={
                  Number(kpis?.overdue_receivables ?? 0) > 0
                    ? `davon überfällig: ${formatMoney(kpis?.overdue_receivables)}`
                    : undefined
                }
              />
              <StatTile
                label="Nicht abgerechnet"
                value={formatMoney(kpis?.unbilled_value)}
                hint={`${formatHours((kpis?.unbilled_seconds ?? 0) / 3600)} offen`}
              />
              <StatTile label="Entwürfe" value={formatMoney(kpis?.draft_total)} />
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <ReservePanel reserve={reserve} />
              </div>
              <div className="space-y-4">
                <BreakdownPanel
                  title="Abgerechnete Leistung nach Kunde"
                  rows={dashboard?.breakdown.by_client ?? []}
                />
                <BreakdownPanel
                  title="Abgerechnete Leistung nach Leistungsart"
                  rows={dashboard?.breakdown.by_service ?? []}
                />
              </div>
            </div>

            <ScenarioPanel baseReserve={reserve} />
          </>
        )}
      </div>
    </>
  );
}

function ReservePanel({ reserve }: { reserve: ReserveForecast | undefined }) {
  if (!reserve) {
    return (
      <Panel>
        <PanelBody>
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        </PanelBody>
      </Panel>
    );
  }
  if (!reserve.available) {
    return (
      <Panel>
        <PanelHeader>
          <PanelTitle>Rücklagenprognose</PanelTitle>
        </PanelHeader>
        <PanelBody>
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
            {reserve.message}
          </p>
        </PanelBody>
      </Panel>
    );
  }

  const gap = Number(reserve.reserve_gap ?? 0);

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          <span className="inline-flex items-center gap-1.5">
            <PiggyBank className="size-4" aria-hidden /> Rücklagenprognose {reserve.tax_year}
          </span>
        </PanelTitle>
        <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
          Regelversion {reserve.rule_version}
        </span>
      </PanelHeader>
      <PanelBody className="space-y-4">
        {reserve.limitations && reserve.limitations.length > 0 ? (
          <div className="rounded-[var(--radius-sm)] border border-[var(--color-warning)] bg-[var(--color-warning-soft)] p-3">
            <div className="mb-1.5 flex items-center gap-1.5 text-[length:var(--text-xs)] font-semibold text-[var(--color-warning)]">
              <AlertTriangle className="size-3.5" aria-hidden /> Grenzen dieser Prognose
            </div>
            <ul className="space-y-1 pl-4 text-[length:var(--text-2xs)] text-[var(--color-ink-muted)]">
              {reserve.limitations.map((limitation) => (
                <li key={limitation} className="list-disc">
                  {limitation}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-3">
          <StatTile
            label="Empfohlene Rücklage"
            value={formatMoney(reserve.recommended_reserve)}
            tone="warning"
          />
          <StatTile
            label={gap > 0 ? 'Noch zurückzulegen' : 'Rücklage gedeckt'}
            value={formatMoney(Math.abs(gap).toFixed(2))}
            tone={gap > 0 ? 'danger' : 'success'}
            hint={`Prognostizierter Jahresgewinn: ${formatMoney(reserve.projected_annual_profit)}`}
          />
        </div>

        {/* The transparent, step-by-step derivation — the brief's core need. */}
        <div>
          <div className="mb-1.5 text-[length:var(--text-xs)] font-medium text-[var(--color-ink-muted)]">
            Berechnung Schritt für Schritt
          </div>
          <DataTable>
            <tbody>
              {(reserve.trace ?? []).map((step: TraceStep, index) => (
                <tr key={index} className="last:[&>td]:border-b-0">
                  <Td>
                    <div className="text-[length:var(--text-sm)]">{step.label}</div>
                    {step.detail ? (
                      <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                        {step.detail}
                      </div>
                    ) : null}
                  </Td>
                  <Td className="tabular text-right font-medium">{formatMoney(step.value)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>

        {reserve.sources && reserve.sources.length > 0 ? (
          <details className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            <summary className="cursor-pointer">Quellen</summary>
            <ul className="mt-1 space-y-0.5 pl-4">
              {reserve.sources.map((source) => (
                <li key={source.field}>
                  {source.source} — {source.note}
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        <div className="flex gap-2 rounded-[var(--radius-sm)] border border-[var(--color-warning)] bg-[var(--color-warning-soft)] p-2.5 text-[length:var(--text-2xs)] text-[var(--color-warning)]">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <p>{reserve.disclaimer}</p>
        </div>
      </PanelBody>
    </Panel>
  );
}

function BreakdownPanel({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; value: string }[];
}) {
  const total = rows.reduce((sum, row) => sum + Number(row.value), 0);
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>{title}</PanelTitle>
      </PanelHeader>
      <PanelBody>
        {rows.length === 0 ? (
          <p className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            Keine Daten.
          </p>
        ) : (
          <ul className="space-y-2">
            {rows.map((row) => {
              const pct = total > 0 ? (Number(row.value) / total) * 100 : 0;
              return (
                <li key={row.label}>
                  <div className="mb-0.5 flex items-baseline justify-between gap-2 text-[length:var(--text-sm)]">
                    <span className="min-w-0 truncate">{row.label}</span>
                    <span className="tabular font-medium">{formatMoney(row.value)}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-panel-sunken)]">
                    <div
                      className="h-full rounded-full bg-[var(--color-brand)]"
                      style={{ width: `${pct}%` }}
                    />
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

function ScenarioPanel({ baseReserve }: { baseReserve: ReserveForecast | undefined }) {
  const scenario = useReserveScenario();
  const [profit, setProfit] = React.useState('');

  const baseProfit = Number(baseReserve?.projected_annual_profit ?? 0);
  const result = scenario.data;

  const run = (value: number) => {
    setProfit(String(value));
    scenario.mutate({ annual_profit: value });
  };

  const presets =
    baseProfit > 0
      ? [
          { label: '−20 %', value: Math.round(baseProfit * 0.8) },
          { label: 'Aktuell', value: Math.round(baseProfit) },
          { label: '+20 %', value: Math.round(baseProfit * 1.2) },
          { label: '+50 %', value: Math.round(baseProfit * 1.5) },
        ]
      : [
          { label: '30.000 €', value: 30000 },
          { label: '50.000 €', value: 50000 },
          { label: '75.000 €', value: 75000 },
          { label: '100.000 €', value: 100000 },
        ];

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Szenarien</PanelTitle>
        <span className="inline-flex items-center gap-1 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
          <Info className="size-3" aria-hidden /> Planungsmodell, unverbindlich
        </span>
      </PanelHeader>
      <PanelBody className="space-y-3">
        <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
          Wie ändert sich die empfohlene Rücklage bei anderem Jahresgewinn?
        </p>
        <div className="flex flex-wrap items-end gap-2">
          {presets.map((preset) => (
            <button
              key={preset.label}
              type="button"
              onClick={() => run(preset.value)}
              className="rounded-[var(--radius-sm)] border border-[var(--color-line)] px-3 py-1.5 text-[length:var(--text-sm)] transition-colors hover:border-[var(--color-brand)] hover:bg-[var(--color-brand-subtle)]"
            >
              {preset.label}
            </button>
          ))}
          <div className="flex items-end gap-2">
            <div>
              <Label htmlFor="scenario-profit">Eigener Gewinn (€)</Label>
              <Input
                id="scenario-profit"
                type="number"
                value={profit}
                onChange={(event) => setProfit(event.target.value)}
                className="w-32"
                placeholder="z. B. 60000"
              />
            </div>
            <button
              type="button"
              onClick={() => profit && run(Number(profit))}
              className="h-8 rounded-[var(--radius-sm)] bg-[var(--color-brand)] px-3 text-[length:var(--text-sm)] font-medium text-white transition-colors hover:bg-[var(--color-brand-hover)]"
            >
              Berechnen
            </button>
          </div>
        </div>

        {result?.available ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Jahresgewinn" value={formatMoney(result.projected_annual_profit)} />
            <StatTile
              label={
                result.legal_form === 'ug' || result.legal_form === 'gmbh'
                  ? 'Körperschaftsteuer'
                  : 'Einkommensteuer'
              }
              value={formatMoney(
                result.legal_form === 'ug' || result.legal_form === 'gmbh'
                  ? result.corporate_tax
                  : result.income_tax,
              )}
            />
            <StatTile label="USt-Reserve" value={formatMoney(result.vat_reserve)} />
            <StatTile
              label="Empfohlene Rücklage"
              value={formatMoney(result.recommended_reserve)}
              tone="warning"
            />
          </div>
        ) : null}
      </PanelBody>
    </Panel>
  );
}
