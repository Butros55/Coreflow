'use client';

import { ArrowLeft, SquareKanban } from 'lucide-react';
import Link from 'next/link';
import { useParams } from 'next/navigation';

import { PageHeader } from '@/components/layout/app-shell';
import { DetailErrorState } from '@/components/ui/detail-error';
import { Button } from '@/components/ui/button';
import { DataTable, Td, Th } from '@/components/ui/group-bar';
import { Panel, PanelBody, PanelHeader, PanelTitle, StatTile } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import { PROJECT_STATUS_LABELS, useProject, useSprints } from '@/lib/api/projects';
import { formatHours, formatMoney } from '@/lib/utils';

const BILLING_LABELS = {
  hourly: 'Nach Aufwand',
  fixed: 'Festpreis',
  retainer: 'Retainer',
  non_billable: 'Nicht abrechenbar',
} as const;

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: project, isLoading, error } = useProject(params.id);
  const { data: sprintsData } = useSprints(params.id);
  const sprints = sprintsData?.results ?? [];

  if (isLoading) {
    return (
      <div className="p-5 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</div>
    );
  }
  if (error || !project) {
    return (
      <DetailErrorState
        error={error}
        entityLabel="Projekt"
        backHref="/projects"
        backLabel="Alle Projekte"
      />
    );
  }

  const logged = project.stats.logged_seconds / 3600;
  const budget = project.budget_hours ? Number(project.budget_hours) : null;
  const budgetUsed = budget ? Math.min(Math.round((logged / budget) * 100), 999) : null;

  return (
    <>
      <PageHeader
        title={project.name}
        description={`${project.client_name} · ${BILLING_LABELS[project.billing_model]}`}
        actions={
          <div className="flex items-center gap-2">
            <StatusTint tone={project.status === 'active' ? 'done' : 'hold'}>
              {PROJECT_STATUS_LABELS[project.status]}
            </StatusTint>
            {project.default_board ? (
              <Button variant="primary" size="sm" asChild>
                <Link href={`/boards/${project.default_board}`}>
                  <SquareKanban aria-hidden /> Zum Board
                </Link>
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" asChild>
              <Link href="/projects">
                <ArrowLeft aria-hidden /> Alle Projekte
              </Link>
            </Button>
          </div>
        }
      >
        <div className="pb-4" />
      </PageHeader>

      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Offene Aufgaben" value={project.stats.open_tasks} />
          <StatTile label="Erledigt" value={project.stats.done_tasks} />
          <StatTile
            label="Erfasste Zeit"
            value={formatHours(logged)}
            hint={budget !== null ? `von ${formatHours(budget)} Budget` : undefined}
            tone={budgetUsed !== null && budgetUsed > 100 ? 'danger' : 'default'}
          />
          <StatTile
            label={project.budget_amount ? 'Budget (€)' : 'Budgetauslastung'}
            value={
              project.budget_amount
                ? formatMoney(project.budget_amount)
                : budgetUsed !== null
                  ? `${budgetUsed} %`
                  : '—'
            }
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          {project.phases.length > 0 ? (
            <Panel>
              <PanelHeader>
                <PanelTitle>Phasen</PanelTitle>
              </PanelHeader>
              <DataTable>
                <thead>
                  <tr>
                    <Th>Phase</Th>
                    <Th>Status</Th>
                    <Th className="text-right">Geplant (h)</Th>
                  </tr>
                </thead>
                <tbody>
                  {project.phases.map((phase) => (
                    <tr key={phase.id} className="last:[&>td]:border-b-0">
                      <Td className="font-medium">{phase.name}</Td>
                      <Td>
                        <StatusTint
                          tone={
                            phase.status === 'completed'
                              ? 'done'
                              : phase.status === 'active'
                                ? 'progress'
                                : 'hold'
                          }
                        >
                          {phase.status === 'completed'
                            ? 'Abgeschlossen'
                            : phase.status === 'active'
                              ? 'Aktiv'
                              : 'Geplant'}
                        </StatusTint>
                      </Td>
                      <Td className="tabular text-right">
                        {phase.planned_hours ? formatHours(phase.planned_hours) : '—'}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </Panel>
          ) : null}

          <Panel>
            <PanelHeader>
              <PanelTitle>Details</PanelTitle>
            </PanelHeader>
            <PanelBody>
              {project.description ? (
                <p className="mb-3 text-[length:var(--text-sm)] whitespace-pre-wrap">
                  {project.description}
                </p>
              ) : null}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[length:var(--text-sm)]">
                <div>
                  <dt className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    Start
                  </dt>
                  <dd>
                    {project.start_date
                      ? new Date(project.start_date).toLocaleDateString('de-DE')
                      : '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    Zieldatum
                  </dt>
                  <dd>
                    {project.target_date
                      ? new Date(project.target_date).toLocaleDateString('de-DE')
                      : '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    Projektleitung
                  </dt>
                  <dd>{project.lead?.full_name ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    Stundensatz
                  </dt>
                  <dd>
                    {project.default_hourly_rate
                      ? formatMoney(project.default_hourly_rate)
                      : 'Kunden-/Workspace-Standard'}
                  </dd>
                </div>
                {sprints.length > 0 ? (
                  <div className="col-span-2">
                    <dt className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                      Sprints
                    </dt>
                    <dd className="mt-1 flex flex-wrap gap-1.5">
                      {sprints.map((sprint) => (
                        <StatusTint
                          key={sprint.id}
                          tone={sprint.status === 'active' ? 'progress' : 'neutral'}
                        >
                          {sprint.name}
                        </StatusTint>
                      ))}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  );
}
