'use client';

import { X } from 'lucide-react';
import * as React from 'react';

import { CommandPalette } from '@/components/layout/command-palette';
import { Sidebar } from '@/components/layout/sidebar';
import { Topbar } from '@/components/layout/topbar';
import { Button } from '@/components/ui/button';
import { usePersistedBoolean } from '@/lib/persisted-state';
import { cn } from '@/lib/utils';

const COLLAPSE_STORAGE_KEY = 'coreflow.sidebar.collapsed';

/**
 * The authenticated layout: fixed left nav, topbar, scrollable main.
 *
 * Desktop-first per the reference designs, but the sidebar becomes an overlay
 * drawer below `md` rather than being hidden — a freelancer checking a client on
 * a phone still needs to navigate.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = usePersistedBoolean(COLLAPSE_STORAGE_KEY, false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [paletteOpen, setPaletteOpen] = React.useState(false);

  const toggleCollapsed = React.useCallback(
    () => setCollapsed(!collapsed),
    [collapsed, setCollapsed],
  );

  // Close the mobile drawer on Escape.
  React.useEffect(() => {
    if (!mobileNavOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileNavOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [mobileNavOpen]);

  return (
    <div className="flex h-dvh overflow-hidden bg-[var(--color-canvas)]">
      <Sidebar collapsed={collapsed} onToggle={toggleCollapsed} className="hidden md:flex" />

      {mobileNavOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/60"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Navigation schließen"
          />
          <div className="absolute top-0 left-0 h-full">
            <Sidebar collapsed={false} onToggle={() => setMobileNavOpen(false)} />
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-2.5 right-3 text-white"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Navigation schließen"
          >
            <X aria-hidden />
          </Button>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          onOpenCommandPalette={() => setPaletteOpen(true)}
          onOpenMobileNav={() => setMobileNavOpen(true)}
        />
        <main className={cn('flex-1 overflow-y-auto')}>{children}</main>
      </div>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}

/**
 * Consistent page header: title, optional description, right-aligned actions.
 *
 * Sits directly on the canvas — no chrome bar. The soft background does the
 * separating; the header is just typography with room to breathe.
 */
export function PageHeader({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="px-5 pt-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-[length:var(--text-2xl)] font-semibold tracking-tight">
            {title}
          </h1>
          {description ? (
            <p className="mt-0.5 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}
