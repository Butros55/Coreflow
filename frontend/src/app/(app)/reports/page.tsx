'use client';

import { BarChart3 } from 'lucide-react';
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { PageHeader } from '@/components/layout/app-shell';
import { EmptyState, Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { useFinanceDashboard, type BreakdownRow } from '@/lib/api/finance';
import { formatMoney } from '@/lib/utils';

const CHART_COLORS = [
  'var(--color-group-1)',
  'var(--color-group-2)',
  'var(--color-group-3)',
  'var(--color-group-4)',
  'var(--color-group-5)',
  'var(--color-group-6)',
  'var(--color-group-7)',
  'var(--color-group-8)',
];

export default function ReportsPage() {
  const { data, isLoading } = useFinanceDashboard();

  const byClient = data?.breakdown.by_client ?? [];
  const byService = data?.breakdown.by_service ?? [];
  const hasData = byClient.length > 0 || byService.length > 0;

  return (
    <>
      <PageHeader title="Berichte" description={`Auswertungen ${data?.year ?? ''}`}>
        <div className="pb-4" />
      </PageHeader>

      <div className="p-5">
        {isLoading ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : !hasData ? (
          <EmptyState
            icon={<BarChart3 className="size-8" aria-hidden />}
            title="Noch keine Auswertungsdaten"
            description="Sobald Rechnungen gestellt und Zeiten abgerechnet sind, erscheinen hier Umsatzauswertungen."
          />
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel>
              <PanelHeader>
                <PanelTitle>Umsatz nach Kunde</PanelTitle>
              </PanelHeader>
              <PanelBody>
                <BarBreakdown rows={byClient} />
              </PanelBody>
            </Panel>

            <Panel>
              <PanelHeader>
                <PanelTitle>Umsatz nach Leistungsart</PanelTitle>
              </PanelHeader>
              <PanelBody>
                <PieBreakdown rows={byService} />
              </PanelBody>
            </Panel>
          </div>
        )}
      </div>
    </>
  );
}

function BarBreakdown({ rows }: { rows: BreakdownRow[] }) {
  const data = rows.map((row) => ({ label: row.label, value: Number(row.value) }));
  if (data.length === 0) {
    return (
      <p className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">Keine Daten.</p>
    );
  }
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
          <XAxis
            type="number"
            tickFormatter={(v) => `${Math.round(v / 1000)}k`}
            stroke="var(--color-ink-subtle)"
            fontSize={11}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={110}
            stroke="var(--color-ink-subtle)"
            fontSize={11}
            tickFormatter={(v: string) => (v.length > 16 ? `${v.slice(0, 15)}…` : v)}
          />
          <Tooltip
            cursor={{ fill: 'var(--color-panel-raised)' }}
            contentStyle={{
              background: 'var(--color-panel-raised)',
              border: '1px solid var(--color-line)',
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(value) => [formatMoney(Number(value).toFixed(2)), 'Umsatz']}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {data.map((_, index) => (
              <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function PieBreakdown({ rows }: { rows: BreakdownRow[] }) {
  const data = rows.map((row) => ({ label: row.label, value: Number(row.value) }));
  if (data.length === 0) {
    return (
      <p className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">Keine Daten.</p>
    );
  }
  const total = data.reduce((sum, d) => sum + d.value, 0);
  return (
    <div className="flex flex-col items-center gap-3 sm:flex-row">
      <div className="h-48 w-48 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="label"
              innerRadius={45}
              outerRadius={80}
              paddingAngle={2}
            >
              {data.map((_, index) => (
                <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: 'var(--color-panel-raised)',
                border: '1px solid var(--color-line)',
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(value) => [formatMoney(Number(value).toFixed(2)), 'Umsatz']}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="flex-1 space-y-1.5">
        {data.map((row, index) => (
          <li key={row.label} className="flex items-center gap-2 text-[length:var(--text-sm)]">
            <span
              className="size-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }}
              aria-hidden
            />
            <span className="min-w-0 flex-1 truncate">{row.label}</span>
            <span className="tabular text-[var(--color-ink-muted)]">
              {total > 0 ? `${Math.round((row.value / total) * 100)}%` : '—'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
