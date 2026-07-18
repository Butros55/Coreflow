'use client';

import { ArrowLeft, SearchX, TriangleAlert } from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { useSession } from '@/lib/session';

/**
 * Terminal state for a detail page whose object could not be loaded.
 *
 * A dangling id is normal life, not an anomaly: links survive seed resets,
 * objects get deleted (locally or in Lexware), and an id from workspace A is
 * deliberately invisible while workspace B is active. Spinning forever on
 * "Lädt…" made all of those look like data loss — this explains instead.
 */
export function DetailErrorState({
  error,
  entityLabel,
  backHref,
  backLabel,
}: {
  error: unknown;
  entityLabel: string;
  backHref: string;
  backLabel: string;
}) {
  const { data: session } = useSession();
  const notFound = error instanceof ApiError && error.status === 404;
  const workspaceName = session?.workspace?.name;

  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <div className="w-full max-w-md text-center">
        {notFound ? (
          <SearchX className="mx-auto mb-3 size-8 text-[var(--color-ink-subtle)]" aria-hidden />
        ) : (
          <TriangleAlert className="mx-auto mb-3 size-8 text-[var(--color-warning)]" aria-hidden />
        )}
        <h2 className="mb-1 text-[length:var(--text-lg)] font-semibold">
          {notFound
            ? `${entityLabel} nicht gefunden`
            : `${entityLabel} konnte nicht geladen werden`}
        </h2>
        <p className="mb-4 text-[length:var(--text-sm)] leading-relaxed text-[var(--color-ink-muted)]">
          {notFound ? (
            <>
              Der Datensatz existiert nicht
              {workspaceName ? (
                <>
                  {' '}
                  im aktiven Workspace <strong>„{workspaceName}“</strong>
                </>
              ) : null}
              . Er wurde gelöscht, gehört zu einem anderen Workspace (oben links wechseln) oder der
              Link stammt aus einem früheren Datenbestand.
            </>
          ) : (
            <>Ein unerwarteter Fehler ist aufgetreten. Versuche es erneut.</>
          )}
        </p>
        <div className="flex items-center justify-center gap-2">
          <Button variant="secondary" size="sm" asChild>
            <Link href={backHref}>
              <ArrowLeft aria-hidden /> {backLabel}
            </Link>
          </Button>
          {!notFound ? (
            <Button variant="ghost" size="sm" onClick={() => window.location.reload()}>
              Neu laden
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
