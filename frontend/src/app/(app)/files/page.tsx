'use client';

import { Download, File, FileText, Trash2, Upload } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/app-shell';
import { Button } from '@/components/ui/button';
import { DeleteConfirmationDialog } from '@/components/ui/delete-confirmation-dialog';
import { ClickableRow, DataTable, Td, Th } from '@/components/ui/group-bar';
import { Input } from '@/components/ui/input';
import { EmptyState, Panel } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import {
  fileDownloadUrl,
  useDeleteFile,
  useFiles,
  useUploadFile,
  type StoredFile,
} from '@/lib/api/files';
import { usePermissions } from '@/lib/session';

export default function FilesPage() {
  const permissions = usePermissions();
  const [search, setSearch] = React.useState('');
  const { data, isLoading } = useFiles({ search: search || undefined });
  const files = data?.results ?? [];

  const upload = useUploadFile();
  const inputRef = React.useRef<HTMLInputElement>(null);

  const onPick = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    upload.mutate(
      { file },
      {
        onSuccess: () => toast.success(`„${file.name}“ hochgeladen.`),
        onError: (error) => toast.error(error.message),
      },
    );
    event.target.value = '';
  };

  return (
    <>
      <PageHeader
        title="Dateien"
        description={`${data?.count ?? '…'} Dateien`}
        actions={
          permissions.can_write ? (
            <>
              <input ref={inputRef} type="file" hidden onChange={onPick} />
              <Button
                variant="primary"
                onClick={() => inputRef.current?.click()}
                loading={upload.isPending}
              >
                <Upload aria-hidden /> Hochladen
              </Button>
            </>
          ) : undefined
        }
      >
        <div className="pt-3 pb-3">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Suchen…"
            className="max-w-xs"
            aria-label="Dateien durchsuchen"
          />
        </div>
      </PageHeader>

      <div className="p-5">
        {isLoading ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : files.length === 0 ? (
          <EmptyState
            icon={<File className="size-8" aria-hidden />}
            title={search ? 'Keine Treffer' : 'Noch keine Dateien'}
            description={search ? undefined : 'Lade Verträge, Angebote oder andere Dokumente hoch.'}
            action={
              permissions.can_write && !search ? (
                <Button variant="primary" onClick={() => inputRef.current?.click()}>
                  <Upload aria-hidden /> Hochladen
                </Button>
              ) : undefined
            }
          />
        ) : (
          <Panel>
            <DataTable>
              <thead>
                <tr>
                  <Th className="w-[40%]">Datei</Th>
                  <Th>Typ</Th>
                  <Th className="text-right">Größe</Th>
                  <Th>Hochgeladen</Th>
                  <Th>Von</Th>
                  {permissions.can_write ? <Th className="w-20" aria-label="Aktionen" /> : null}
                </tr>
              </thead>
              <tbody>
                {files.map((file) => (
                  <FileRow key={file.id} file={file} canWrite={permissions.can_write} />
                ))}
              </tbody>
            </DataTable>
          </Panel>
        )}
      </div>
    </>
  );
}

function FileRow({ file, canWrite }: { file: StoredFile; canWrite: boolean }) {
  const remove = useDeleteFile();
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const ext = file.filename.includes('.') ? file.filename.split('.').pop()!.toUpperCase() : '—';

  return (
    <>
      <ClickableRow onClick={() => window.open(fileDownloadUrl(file.id), '_blank')}>
        <Td>
          <span className="inline-flex items-center gap-2">
            <FileText className="size-4 shrink-0 text-[var(--color-ink-subtle)]" aria-hidden />
            <span className="font-medium">{file.filename}</span>
            {file.is_generated ? <StatusTint tone="todo">System</StatusTint> : null}
          </span>
          {file.description ? (
            <div className="ml-6 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
              {file.description}
            </div>
          ) : null}
        </Td>
        <Td className="text-[var(--color-ink-muted)]">{ext}</Td>
        <Td className="tabular text-right text-[var(--color-ink-muted)]">{file.size_display}</Td>
        <Td className="text-[var(--color-ink-muted)]">
          {new Date(file.created_at).toLocaleDateString('de-DE')}
        </Td>
        <Td className="text-[var(--color-ink-muted)]">{file.uploaded_by?.full_name ?? '—'}</Td>
        {canWrite ? (
          <Td className="text-right" onClick={(e) => e.stopPropagation()}>
            <span className="inline-flex gap-1">
              <a
                href={fileDownloadUrl(file.id)}
                className="rounded p-1 text-[var(--color-ink-subtle)] hover:text-[var(--color-ink)]"
                aria-label="Herunterladen"
              >
                <Download className="size-3.5" aria-hidden />
              </a>
              {!file.is_generated ? (
                <button
                  type="button"
                  onClick={() => setDeleteOpen(true)}
                  aria-label="Löschen"
                  className="rounded p-1 text-[var(--color-ink-subtle)] hover:text-[var(--color-danger)]"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              ) : null}
            </span>
          </Td>
        ) : null}
      </ClickableRow>
      <DeleteConfirmationDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Datei löschen?"
        itemName={file.filename}
        isPending={remove.isPending}
        onConfirm={() =>
          remove.mutate(file.id, {
            onSuccess: () => {
              toast.success('Datei gelöscht.');
              setDeleteOpen(false);
            },
            onError: (error) => toast.error(error.message),
          })
        }
      />
    </>
  );
}
