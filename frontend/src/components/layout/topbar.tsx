'use client';

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Bell, LogOut, Menu, Search, User as UserIcon } from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { useLogout, useSession } from '@/lib/session';
import { cn, colorFromId, GROUP_COLORS } from '@/lib/utils';

export function Topbar({
  onOpenCommandPalette,
  onOpenMobileNav,
}: {
  onOpenCommandPalette: () => void;
  onOpenMobileNav: () => void;
}) {
  const { data: session } = useSession();
  const logout = useLogout();
  const user = session?.user;

  return (
    <header className="flex h-[var(--spacing-topbar)] shrink-0 items-center gap-2 border-b border-[var(--color-line)] bg-[var(--color-surface)] px-3">
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        onClick={onOpenMobileNav}
        aria-label="Navigation öffnen"
      >
        <Menu aria-hidden />
      </Button>

      {/* Search opens the command palette rather than being a second input —
          one entry point for "find anything" is easier to learn than two. */}
      <button
        type="button"
        onClick={onOpenCommandPalette}
        className={cn(
          'flex h-8 w-full max-w-md items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--color-line)] bg-[var(--color-panel-sunken)] px-2.5 text-left text-[length:var(--text-sm)] text-[var(--color-ink-subtle)]',
          'transition-colors hover:border-[var(--color-line-strong)]',
        )}
      >
        <Search className="size-3.5 shrink-0" aria-hidden />
        <span className="flex-1 truncate">Suchen…</span>
        <kbd className="hidden shrink-0 rounded-[var(--radius-xs)] border border-[var(--color-line)] bg-[var(--color-panel)] px-1.5 py-0.5 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)] sm:inline-block">
          Ctrl K
        </kbd>
      </button>

      <div className="flex-1" />

      <Button variant="ghost" size="icon" aria-label="Benachrichtigungen" asChild>
        <Link href="/notifications">
          <Bell aria-hidden />
        </Link>
      </Button>

      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            className="flex size-7 items-center justify-center rounded-full text-[length:var(--text-xs)] font-semibold text-white transition-opacity hover:opacity-85"
            style={{
              backgroundColor: user?.avatar_color || colorFromId(user?.id ?? '0', GROUP_COLORS),
            }}
            aria-label="Benutzermenü"
          >
            {user?.initials ?? '··'}
          </button>
        </DropdownMenu.Trigger>

        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={6}
            className="z-50 min-w-52 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-panel-raised)] p-1 shadow-[var(--shadow-popover)]"
          >
            <div className="px-2 py-1.5">
              <div className="truncate text-[length:var(--text-sm)] font-medium">
                {user?.full_name}
              </div>
              <div className="truncate text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
                {user?.email}
              </div>
            </div>
            <DropdownMenu.Separator className="my-1 h-px bg-[var(--color-line)]" />
            <DropdownMenu.Item asChild>
              <Link
                href="/settings/profile"
                className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-xs)] px-2 py-1.5 text-[length:var(--text-sm)] outline-none data-[highlighted]:bg-[var(--color-panel)]"
              >
                <UserIcon className="size-3.5" aria-hidden />
                Profil
              </Link>
            </DropdownMenu.Item>
            <DropdownMenu.Separator className="my-1 h-px bg-[var(--color-line)]" />
            <DropdownMenu.Item
              onSelect={() => logout.mutate()}
              className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-xs)] px-2 py-1.5 text-[length:var(--text-sm)] text-[var(--color-danger)] outline-none data-[highlighted]:bg-[var(--color-danger-soft)]"
            >
              <LogOut className="size-3.5" aria-hidden />
              Abmelden
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </header>
  );
}
