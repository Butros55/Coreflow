'use client';

import { Square, Timer as TimerIcon } from 'lucide-react';
import Link from 'next/link';
import * as React from 'react';
import { toast } from 'sonner';

import { useStopTimer, useTimer } from '@/lib/api/time';
import { formatDuration } from '@/lib/utils';

/**
 * The globally visible running timer (topbar).
 *
 * Elapsed time ticks locally off `started_at`; the query only re-syncs across
 * tabs/devices. Rendering nothing when no timer runs is deliberate — a dead
 * "0:00:00" would just be noise.
 */
export function TimerWidget() {
  const { data } = useTimer();
  const stopTimer = useStopTimer();
  const running = data?.running ?? null;

  const [elapsed, setElapsed] = React.useState(0);

  React.useEffect(() => {
    if (!running) return;
    const startedAt = new Date(running.started_at).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [running]);

  if (!running) return null;

  const label = running.project_name || running.client_name;

  return (
    <div className="flex h-8 items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--color-status-progress)] bg-[var(--color-status-progress-soft)] pr-1 pl-2.5">
      <TimerIcon className="size-3.5 text-[var(--color-status-progress)]" aria-hidden />
      <Link
        href="/time"
        className="flex items-baseline gap-2 text-[length:var(--text-sm)] hover:underline"
        title={running.description || label}
      >
        <span className="tabular font-semibold text-[var(--color-status-progress)]">
          {formatDuration(elapsed)}
        </span>
        <span className="hidden max-w-40 truncate text-[var(--color-ink-muted)] sm:inline">
          {label}
        </span>
      </Link>
      <button
        type="button"
        onClick={() =>
          stopTimer.mutate(undefined, {
            onSuccess: (entry) =>
              toast.success(`Timer gestoppt: ${formatDuration(entry.duration_seconds)}`),
            onError: () => toast.error('Timer konnte nicht gestoppt werden.'),
          })
        }
        disabled={stopTimer.isPending}
        aria-label="Timer stoppen"
        className="flex size-6 items-center justify-center rounded-[var(--radius-xs)] text-[var(--color-status-progress)] transition-colors hover:bg-[var(--color-status-progress)] hover:text-white disabled:opacity-50"
      >
        <Square className="size-3" fill="currentColor" aria-hidden />
      </button>
    </div>
  );
}
