'use client';

import { Loader2 } from 'lucide-react';

import { AppShell } from '@/components/layout/app-shell';
import { WorkspaceOnboarding } from '@/components/layout/create-workspace';
import { useRequireSession } from '@/lib/session';

/**
 * Layout for every authenticated route.
 *
 * This is a UX gate, not a security boundary: it avoids rendering a shell for a
 * logged-out user. Authorisation is enforced by the API on every request — a
 * user who defeats this sees an empty shell and 401s, not data.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { session, isLoading } = useRequireSession();

  if (isLoading || session === undefined) {
    return (
      <div className="flex h-dvh items-center justify-center bg-[var(--color-canvas)]">
        <Loader2 className="size-5 animate-spin text-[var(--color-ink-subtle)]" aria-label="Lädt" />
      </div>
    );
  }

  // useRequireSession is redirecting; render nothing rather than flashing UI.
  if (session === null) return null;

  // Fresh account without any workspace (e.g. created via createsuperuser):
  // the app is unusable until one exists, so onboarding takes over.
  if (session.workspaces.length === 0) return <WorkspaceOnboarding />;

  return <AppShell>{children}</AppShell>;
}
