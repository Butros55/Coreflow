'use client';

import { useMutation } from '@tanstack/react-query';
import { DatabaseBackup, Download, FileUp, ShieldAlert } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Panel, PanelBody, PanelHeader, PanelTitle } from '@/components/ui/panel';
import { api } from '@/lib/api/client';

interface ExportPayload {
  format: string;
  schema_version: number;
  exported_at: string;
  counts: Record<string, number>;
  notes?: string[];
}

interface ImportResult {
  imported: Record<string, number>;
  skipped: Record<string, number>;
}

/** Human labels for the technical model names in the export counts. */
const MODEL_LABELS: Record<string, string> = {
  'crm.Client': 'Kunden',
  'crm.ClientContact': 'Kontakte',
  'crm.ClientNote': 'Notizen',
  'crm.ClientActivity': 'Aktivitäten',
  'timetracking.ServiceType': 'Leistungsarten',
  'timetracking.TimeEntry': 'Zeiteinträge',
  'projects.Project': 'Projekte',
  'projects.ProjectPhase': 'Projektphasen',
  'projects.Board': 'Boards',
  'projects.Sprint': 'Sprints',
  'projects.Task': 'Aufgaben',
  'projects.TaskComment': 'Kommentare',
  'projects.TaskChecklistItem': 'Checklistenpunkte',
  'invoicing.Invoice': 'Rechnungen',
  'invoicing.InvoiceLine': 'Rechnungspositionen',
  'invoicing.InvoiceTimeEntry': 'Rechnungs-Zeitzuordnungen',
  'scheduling.Appointment': 'Termine',
  'files.StoredFile': 'Datei-Metadaten',
  'finance.TaxProfile': 'Steuerprofile',
  'finance.ReserveTransfer': 'Rücklagen-Überträge',
  'finance.ReserveSnapshot': 'Rücklagen-Snapshots',
  'integrations.ExternalObjectLink': 'Integrations-Verknüpfungen',
  'integrations.SyncJob': 'Sync-Läufe',
  'integrations.WebhookEvent': 'Webhook-Ereignisse',
  'integrations.SyncConflict': 'Sync-Konflikte',
  'integrations.ProviderProfile': 'Integrations-Profile',
};

function modelLabel(key: string): string {
  return MODEL_LABELS[key] ?? key;
}

export function DataTab() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ExportPanel />
      <ImportPanel />
    </div>
  );
}

function ExportPanel() {
  const exportData = useMutation({
    mutationFn: () => api.get<ExportPayload>('/workspace-data/export'),
    onSuccess: (payload) => {
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `coreflow-export-${new Date().toISOString().slice(0, 10)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      const total = Object.values(payload.counts).reduce((sum, count) => sum + count, 0);
      toast.success(`Export erstellt: ${total} Objekte.`);
    },
    onError: (error) => toast.error(error.message),
  });

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          <span className="inline-flex items-center gap-1.5">
            <DatabaseBackup className="size-4" aria-hidden /> Alles exportieren
          </span>
        </PanelTitle>
      </PanelHeader>
      <PanelBody className="space-y-3">
        <p className="text-[length:var(--text-sm)] leading-relaxed text-[var(--color-ink-muted)]">
          Lädt sämtliche Daten dieses Workspaces als JSON-Datei herunter: Kunden, Projekte,
          Aufgaben, Zeiten, Rechnungen, Finanzen, Termine und Integrations-Verknüpfungen. Die Datei
          lässt sich hier jederzeit wieder importieren.
        </p>
        <ul className="list-disc space-y-1 pl-4 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
          <li>Nur die Daten des aktuell angemeldeten Workspaces.</li>
          <li>Datei-Inhalte (Uploads) sind nicht enthalten, nur ihre Metadaten.</li>
          <li>Benutzerkonten und Passwörter sind nicht Teil des Exports.</li>
        </ul>
        <Button
          variant="primary"
          onClick={() => exportData.mutate()}
          loading={exportData.isPending}
        >
          <Download aria-hidden /> Export herunterladen
        </Button>
      </PanelBody>
    </Panel>
  );
}

function ImportPanel() {
  const fileInput = React.useRef<HTMLInputElement>(null);
  const [pending, setPending] = React.useState<{ file: File; payload: ExportPayload } | null>(null);
  const [result, setResult] = React.useState<ImportResult | null>(null);

  const importData = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append('file', file);
      return api.post<ImportResult>('/workspace-data/import', form);
    },
    onSuccess: (data) => {
      setPending(null);
      setResult(data);
      const total = Object.values(data.imported).reduce((sum, count) => sum + count, 0);
      toast.success(`Import abgeschlossen: ${total} Objekte wiederhergestellt.`);
    },
    onError: (error) => toast.error(error.message),
  });

  const onPickFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text()) as ExportPayload;
      if (payload.format !== 'coreflow-workspace-export') {
        toast.error('Das ist keine Coreflow-Exportdatei.');
        return;
      }
      setResult(null);
      setPending({ file, payload });
    } catch {
      toast.error('Keine gültige JSON-Datei.');
    }
  };

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          <span className="inline-flex items-center gap-1.5">
            <FileUp className="size-4" aria-hidden /> Export importieren
          </span>
        </PanelTitle>
      </PanelHeader>
      <PanelBody className="space-y-3">
        <p className="text-[length:var(--text-sm)] leading-relaxed text-[var(--color-ink-muted)]">
          Stellt eine zuvor exportierte Datei in diesem Workspace wieder her. Objekte mit gleicher
          ID werden aktualisiert, fehlende neu angelegt — Daten anderer Workspaces bleiben
          unberührt.
        </p>
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={onPickFile}
        />
        <Button variant="secondary" onClick={() => fileInput.current?.click()}>
          <FileUp aria-hidden /> Datei auswählen…
        </Button>

        {result ? (
          <div className="rounded-[var(--radius-md)] bg-[var(--color-success-soft)] p-3 text-[length:var(--text-xs)] text-[var(--color-success)]">
            Import abgeschlossen:{' '}
            {Object.entries(result.imported)
              .filter(([, count]) => count > 0)
              .map(([key, count]) => `${count} ${modelLabel(key)}`)
              .join(', ') || 'keine Objekte'}
            .
          </div>
        ) : null}
      </PanelBody>

      <Dialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent
          title="Import bestätigen"
          description={
            pending
              ? `Export vom ${new Date(pending.payload.exported_at).toLocaleString('de-DE')}`
              : undefined
          }
        >
          {pending ? (
            <div className="space-y-4">
              <ul className="max-h-48 space-y-1 overflow-y-auto rounded-[var(--radius-md)] bg-[var(--color-panel-sunken)] p-3 text-[length:var(--text-xs)]">
                {Object.entries(pending.payload.counts)
                  .filter(([, count]) => count > 0)
                  .map(([key, count]) => (
                    <li key={key} className="flex justify-between gap-3">
                      <span className="text-[var(--color-ink-muted)]">{modelLabel(key)}</span>
                      <span className="tabular font-medium">{count}</span>
                    </li>
                  ))}
              </ul>
              <div className="flex gap-2 rounded-[var(--radius-md)] bg-[var(--color-warning-soft)] p-2.5 text-[length:var(--text-2xs)] text-[var(--color-warning)]">
                <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <p>
                  Vorhandene Objekte mit gleicher ID werden mit dem Stand aus der Datei
                  überschrieben. Dieser Schritt kann nicht rückgängig gemacht werden.
                </p>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setPending(null)}>
                  Abbrechen
                </Button>
                <Button
                  variant="primary"
                  onClick={() => importData.mutate(pending.file)}
                  loading={importData.isPending}
                >
                  Jetzt importieren
                </Button>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </Panel>
  );
}
