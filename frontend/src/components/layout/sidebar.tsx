'use client';

import { ChevronsLeft, ChevronsRight } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import * as React from 'react';

import { NAV_SECTIONS } from '@/components/layout/nav-items';
import { WorkspaceSwitcher } from '@/components/layout/workspace-switcher';
import { usePermissions } from '@/lib/session';
import { cn } from '@/lib/utils';

export function Sidebar({
  collapsed,
  onToggle,
  className,
}: {
  collapsed: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const pathname = usePathname();
  const permissions = usePermissions();

  const isActive = React.useCallback(
    (href: string) => pathname === href || pathname.startsWith(`${href}/`),
    [pathname],
  );

  return (
    <aside
      className={cn(
        'flex h-full flex-col border-r border-[var(--color-line-subtle)] bg-[var(--color-surface)] transition-[width] duration-150',
        collapsed ? 'w-[var(--spacing-sidebar-collapsed)]' : 'w-[var(--spacing-sidebar)]',
        className,
      )}
      aria-label="Hauptnavigation"
    >
      <div className="flex h-[var(--spacing-topbar)] shrink-0 items-center gap-2.5 px-3">
        <div
          className="bg-brand-gradient flex size-7 shrink-0 items-center justify-center rounded-[var(--radius-md)] text-[length:var(--text-sm)] font-bold text-white shadow-[0_4px_12px_var(--color-brand-ring)]"
          aria-hidden
        >
          C
        </div>
        {!collapsed ? (
          <span className="truncate text-[length:var(--text-lg)] font-semibold tracking-tight">
            Coreflow
          </span>
        ) : null}
      </div>

      {!collapsed ? (
        <div className="px-2 pb-2">
          <WorkspaceSwitcher />
        </div>
      ) : null}

      <nav className="flex-1 scrollbar-none overflow-y-auto px-2 py-3">
        {NAV_SECTIONS.map((section, sectionIndex) => {
          const visible = section.items.filter(
            (item) => !item.requires || permissions[item.requires],
          );
          if (visible.length === 0) return null;

          return (
            <div key={section.title ?? `section-${sectionIndex}`} className="mb-4 last:mb-0">
              {section.title && !collapsed ? (
                <div className="mb-1 px-2 text-[length:var(--text-2xs)] font-semibold tracking-wider text-[var(--color-ink-subtle)] uppercase">
                  {section.title}
                </div>
              ) : null}
              <ul className="space-y-0.5">
                {visible.map((item) => {
                  const active = isActive(item.href);
                  const Icon = item.icon;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? 'page' : undefined}
                        title={collapsed ? item.label : undefined}
                        className={cn(
                          'flex h-8.5 items-center gap-2.5 rounded-[var(--radius-md)] px-2.5 text-[length:var(--text-sm)] transition-colors',
                          collapsed && 'justify-center px-0',
                          active
                            ? 'bg-[var(--color-brand-subtle)] font-medium text-[var(--color-brand)]'
                            : 'text-[var(--color-ink-muted)] hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)]',
                        )}
                      >
                        <Icon className="size-4 shrink-0" aria-hidden />
                        {!collapsed ? <span className="truncate">{item.label}</span> : null}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="border-t border-[var(--color-line-subtle)] p-2">
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? 'Navigation ausklappen' : 'Navigation einklappen'}
          className="flex h-7 w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] text-[var(--color-ink-subtle)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)]"
        >
          {collapsed ? (
            <ChevronsRight className="size-4" aria-hidden />
          ) : (
            <>
              <ChevronsLeft className="size-4" aria-hidden />
              <span className="text-[length:var(--text-xs)]">Einklappen</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
