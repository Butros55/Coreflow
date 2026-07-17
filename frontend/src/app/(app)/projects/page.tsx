'use client';

import { FolderKanban, Plus, Search } from 'lucide-react';
import { useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/app-shell';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { ClickableRow, DataTable, GroupSection, Td, Th } from '@/components/ui/group-bar';
import { Input, Label } from '@/components/ui/input';
import { EmptyState } from '@/components/ui/panel';
import { Select } from '@/components/ui/select';
import { PriorityPill } from '@/components/ui/status-pill';
import { useClients } from '@/lib/api/crm';
import {
  PRIORITY_LABELS,
  PROJECT_STATUS_LABELS,
  useCreateProject,
  useProjects,
  type Project,
  type ProjectStatus,
} from '@/lib/api/projects';
import { usePermissions } from '@/lib/session';
import { formatHours } from '@/lib/utils';

const GROUPS: { status: ProjectStatus; color: string }[] = [
  { status: 'active', color: 'var(--color-status-done)' },
  { status: 'planned', color: 'var(--color-status-todo)' },
  { status: 'on_hold', color: 'var(--color-status-progress)' },
  { status: 'completed', color: 'var(--color-status-hold)' },
  { status: 'cancelled', color: 'var(--color-status-stuck)' },
];

export default function ProjectsPage() {
  const router = useRouter();
  const permissions = usePermissions();
  const [search, setSearch] = React.useState('');
  const [createOpen, setCreateOpen] = React.useState(false);
  const { data, isLoading } = useProjects({ search: search || undefined });
  const projects = data?.results ?? [];

  const groups = GROUPS.map((group) => ({
    ...group,
    projects: projects.filter((project) => project.status === group.status && !project.archived),
  })).filter((group) => group.projects.length > 0);

  return (
    <>
      <PageHeader
        title="Projekte"
        description={`${data?.count ?? '…'} Projekte`}
        actions={
          permissions.can_write ? (
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden /> Neues Projekt
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
              aria-label="Projekte durchsuchen"
            />
          </div>
        </div>
      </PageHeader>

      <div className="p-5">
        {isLoading ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : groups.length === 0 ? (
          <EmptyState
            icon={<FolderKanban className="size-8" aria-hidden />}
            title={search ? 'Keine Treffer' : 'Noch keine Projekte'}
            action={
              permissions.can_write && !search ? (
                <Button variant="primary" onClick={() => setCreateOpen(true)}>
                  <Plus aria-hidden /> Neues Projekt
                </Button>
              ) : undefined
            }
          />
        ) : (
          groups.map((group) => (
            <GroupSection
              key={group.status}
              color={group.color}
              title={PROJECT_STATUS_LABELS[group.status]}
              count={group.projects.length}
            >
              <DataTable>
                <thead>
                  <tr>
                    <Th className="w-[30%]">Projekt</Th>
                    <Th>Kunde</Th>
                    <Th>Priorität</Th>
                    <Th className="text-right">Aufgaben offen</Th>
                    <Th className="text-right">Erfasst</Th>
                    <Th className="text-right">Budget (h)</Th>
                    <Th>Ziel</Th>
                  </tr>
                </thead>
                <tbody>
                  {group.projects.map((project) => (
                    <ProjectRow
                      key={project.id}
                      project={project}
                      onOpen={() => router.push(`/projects/${project.id}`)}
                    />
                  ))}
                </tbody>
              </DataTable>
            </GroupSection>
          ))
        )}
      </div>

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}

function ProjectRow({ project, onOpen }: { project: Project; onOpen: () => void }) {
  const logged = project.stats.logged_seconds / 3600;
  const budget = project.budget_hours ? Number(project.budget_hours) : null;
  const overBudget = budget !== null && logged > budget;

  return (
    <ClickableRow onClick={onOpen} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen()}>
      <Td>
        <span
          className="mr-2 inline-block size-2 rounded-full align-middle"
          style={{ backgroundColor: project.color || 'var(--color-brand)' }}
          aria-hidden
        />
        <span className="font-medium">{project.name}</span>
      </Td>
      <Td className="text-[var(--color-ink-muted)]">{project.client_name}</Td>
      <Td>
        <PriorityPill tone={project.priority}>{PRIORITY_LABELS[project.priority]}</PriorityPill>
      </Td>
      <Td className="tabular text-right">{project.stats.open_tasks}</Td>
      <Td className="tabular text-right">
        <span className={overBudget ? 'font-medium text-[var(--color-danger)]' : ''}>
          {formatHours(logged)}
        </span>
      </Td>
      <Td className="tabular text-right text-[var(--color-ink-muted)]">
        {budget !== null ? formatHours(budget) : '—'}
      </Td>
      <Td className="text-[var(--color-ink-muted)]">
        {project.target_date ? new Date(project.target_date).toLocaleDateString('de-DE') : '—'}
      </Td>
    </ClickableRow>
  );
}

function CreateProjectDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const createProject = useCreateProject();
  const { data: clientsData } = useClients({ archived: false });
  const clients = clientsData?.results ?? [];
  const [name, setName] = React.useState('');
  const [clientId, setClientId] = React.useState('');

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !clientId) return;
    createProject.mutate(
      { name: name.trim(), client: clientId },
      {
        onSuccess: (project) => {
          toast.success(`Projekt „${project.name}“ angelegt.`);
          onOpenChange(false);
          setName('');
          router.push(`/projects/${project.id}`);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Neues Projekt"
        description="Ein Hauptboard wird automatisch mit angelegt."
      >
        <form onSubmit={submit} className="space-y-3">
          <div>
            <Label htmlFor="project-name" required>
              Projektname
            </Label>
            <Input
              id="project-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
              required
            />
          </div>
          <div>
            <Label htmlFor="project-client" required>
              Kunde
            </Label>
            <Select
              id="project-client"
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
              required
            >
              <option value="" disabled>
                Kunde wählen…
              </option>
              {clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button type="submit" variant="primary" loading={createProject.isPending}>
              Anlegen
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
