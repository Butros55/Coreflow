'use client';

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { FolderKanban, Plus, X } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { InvoiceStatusBadge } from '@/components/invoices/invoice-status-badge';
import { Button } from '@/components/ui/button';
import { useAssignInvoiceProject, useInvoices } from '@/lib/api/invoicing';
import { useProjects } from '@/lib/api/projects';
import { formatMoney } from '@/lib/utils';

const MENU_CLASS =
  'z-50 max-h-80 w-72 overflow-y-auto rounded-[var(--radius-lg)] border border-[var(--color-line-subtle)] bg-[var(--color-panel)] p-1 shadow-[var(--shadow-popover)]';

const ITEM_CLASS =
  'flex w-full cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-2 text-left text-[length:var(--text-sm)] outline-none data-[highlighted]:bg-[var(--color-panel-raised)]';

function MenuLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-2.5 pt-1.5 pb-1 text-[length:var(--text-2xs)] font-semibold tracking-wider text-[var(--color-ink-subtle)] uppercase">
      {children}
    </div>
  );
}

function MenuEmpty({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-2.5 py-3 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
      {children}
    </div>
  );
}

/**
 * Plus-button on a project's invoice panel: assign one of the client's
 * unassigned invoices to this project with a single click.
 */
export function AssignInvoiceToProjectMenu({
  projectId,
  clientId,
}: {
  projectId: string;
  clientId: string;
}) {
  const [open, setOpen] = React.useState(false);
  // Fetch lazily: the pool is only needed once the menu opens.
  const { data, isLoading } = useInvoices(
    { client: clientId, unassigned: true },
    { enabled: open },
  );
  const assign = useAssignInvoiceProject();
  const candidates = data?.results ?? [];

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <Button variant="secondary" size="xs" aria-label="Rechnung zuordnen">
          <Plus aria-hidden /> Rechnung zuordnen
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className={MENU_CLASS}>
          <MenuLabel>Unzugeordnete Rechnungen</MenuLabel>
          {isLoading ? (
            <MenuEmpty>Lädt…</MenuEmpty>
          ) : candidates.length === 0 ? (
            <MenuEmpty>
              Keine unzugeordneten Rechnungen für diesen Kunden — alles ist bereits einem Projekt
              zugewiesen.
            </MenuEmpty>
          ) : (
            candidates.map((invoice) => (
              <DropdownMenu.Item
                key={invoice.id}
                className={ITEM_CLASS}
                onSelect={() =>
                  assign.mutate(
                    { invoiceId: invoice.id, projectId },
                    {
                      onSuccess: () => toast.success('Rechnung dem Projekt zugeordnet.'),
                      onError: () => toast.error('Zuordnen fehlgeschlagen.'),
                    },
                  )
                }
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">
                    {invoice.invoice_number || `Entwurf ${invoice.id.slice(0, 8)}`}
                  </div>
                  <div className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    {invoice.invoice_date
                      ? new Date(invoice.invoice_date).toLocaleDateString('de-DE')
                      : 'Ohne Datum'}
                    {' · '}
                    {formatMoney(invoice.gross_amount)}
                  </div>
                </div>
                <InvoiceStatusBadge status={invoice.status} />
              </DropdownMenu.Item>
            ))
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/**
 * Project picker on an invoice (detail page or list row): assign the invoice
 * to one of its client's projects, or clear the assignment.
 */
export function AssignProjectToInvoiceMenu({
  invoiceId,
  clientId,
  currentProjectId,
  trigger,
}: {
  invoiceId: string;
  clientId: string;
  currentProjectId: string | null;
  trigger?: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const { data, isLoading } = useProjects({ client: clientId }, { enabled: open });
  const assign = useAssignInvoiceProject();
  const projects = data?.results ?? [];

  const run = (projectId: string | null, successMessage: string) =>
    assign.mutate(
      { invoiceId, projectId },
      {
        onSuccess: () => toast.success(successMessage),
        onError: () => toast.error('Zuordnen fehlgeschlagen.'),
      },
    );

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        {trigger ?? (
          <Button variant="secondary" size="xs" aria-label="Projekt zuordnen">
            <FolderKanban aria-hidden /> {currentProjectId ? 'Projekt ändern' : 'Projekt zuordnen'}
          </Button>
        )}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className={MENU_CLASS}>
          <MenuLabel>Projekte des Kunden</MenuLabel>
          {isLoading ? (
            <MenuEmpty>Lädt…</MenuEmpty>
          ) : projects.length === 0 ? (
            <MenuEmpty>Dieser Kunde hat noch keine Projekte.</MenuEmpty>
          ) : (
            projects.map((project) => (
              <DropdownMenu.Item
                key={project.id}
                disabled={project.id === currentProjectId}
                className={`${ITEM_CLASS} data-[disabled]:cursor-default data-[disabled]:opacity-50`}
                onSelect={() => run(project.id, `Rechnung „${project.name}" zugeordnet.`)}
              >
                <span
                  className="size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: project.color }}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate">{project.name}</span>
                {project.id === currentProjectId ? (
                  <span className="text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
                    Aktuell
                  </span>
                ) : null}
              </DropdownMenu.Item>
            ))
          )}
          {currentProjectId ? (
            <>
              <DropdownMenu.Separator className="my-1 h-px bg-[var(--color-line-subtle)]" />
              <DropdownMenu.Item
                className={`${ITEM_CLASS} text-[var(--color-danger)] data-[highlighted]:bg-[var(--color-danger-soft)]`}
                onSelect={() => run(null, 'Projektzuordnung entfernt.')}
              >
                <X className="size-3.5" aria-hidden /> Zuordnung entfernen
              </DropdownMenu.Item>
            </>
          ) : null}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
