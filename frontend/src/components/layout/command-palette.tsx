'use client';

import { Command } from 'cmdk';
import { useRouter } from 'next/navigation';
import * as React from 'react';

import { NAV_SECTIONS } from '@/components/layout/nav-items';
import { usePermissions } from '@/lib/session';

/**
 * Global command palette (Ctrl/Cmd+K).
 *
 * Phase 0 ships navigation only. Later phases register entity search (clients,
 * projects, tasks) and actions (start timer, new invoice) into the same surface.
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const permissions = usePermissions();

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  const go = React.useCallback(
    (href: string) => {
      onOpenChange(false);
      router.push(href);
    },
    [onOpenChange, router],
  );

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Befehlspalette"
      className="fixed inset-0 z-50"
    >
      {/* Click-outside affordance. A <button> rather than a div with onClick:
          it is focusable and Enter-activatable for free, and cmdk already
          handles Escape. */}
      <button
        type="button"
        tabIndex={-1}
        className="fixed inset-0 cursor-default bg-black/60 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
        aria-label="Befehlspalette schließen"
      />
      <div className="fixed top-[20%] left-1/2 w-full max-w-lg -translate-x-1/2 px-4">
        <div className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-line-strong)] bg-[var(--color-panel)] shadow-[var(--shadow-popover)]">
          <Command.Input
            placeholder="Springe zu…"
            className="h-11 w-full border-b border-[var(--color-line)] bg-transparent px-4 text-[length:var(--text-base)] text-[var(--color-ink)] outline-none placeholder:text-[var(--color-ink-subtle)]"
          />
          <Command.List className="max-h-80 overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-[length:var(--text-sm)] text-[var(--color-ink-subtle)]">
              Nichts gefunden.
            </Command.Empty>

            {NAV_SECTIONS.map((section, index) => {
              const visible = section.items.filter(
                (item) => !item.requires || permissions[item.requires],
              );
              if (visible.length === 0) return null;
              return (
                <Command.Group
                  key={section.title ?? `group-${index}`}
                  heading={section.title ?? 'Navigation'}
                  className="mb-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[length:var(--text-2xs)] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-[var(--color-ink-subtle)] [&_[cmdk-group-heading]]:uppercase"
                >
                  {visible.map((item) => {
                    const Icon = item.icon;
                    return (
                      <Command.Item
                        key={item.href}
                        value={`${item.label} ${item.href}`}
                        onSelect={() => go(item.href)}
                        className="flex cursor-pointer items-center gap-2.5 rounded-[var(--radius-sm)] px-2 py-2 text-[length:var(--text-sm)] text-[var(--color-ink-muted)] data-[selected=true]:bg-[var(--color-brand-subtle)] data-[selected=true]:text-[var(--color-ink)]"
                      >
                        <Icon className="size-4" aria-hidden />
                        {item.label}
                      </Command.Item>
                    );
                  })}
                </Command.Group>
              );
            })}
          </Command.List>
        </div>
      </div>
    </Command.Dialog>
  );
}
