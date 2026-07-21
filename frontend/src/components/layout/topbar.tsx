'use client';

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { LogOut, Menu, Moon, Search, Sun } from 'lucide-react';

import { TimerWidget } from '@/components/timer/timer-widget';
import { Button } from '@/components/ui/button';
import { useLogout, useSession } from '@/lib/session';
import { useDarkTheme } from '@/lib/theme';
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
  const [dark, setDark] = useDarkTheme();
  const user = session?.user;

  return (
    <header className="flex h-[var(--spacing-topbar)] shrink-0 items-center gap-2 border-b border-[var(--color-line-subtle)] bg-[var(--color-surface)] px-3">
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
          'flex h-9 w-full max-w-md items-center gap-2.5 rounded-full border border-[var(--color-line)] bg-[var(--color-panel-sunken)] px-3.5 text-left text-[length:var(--text-sm)] text-[var(--color-ink-subtle)]',
          'transition-[border-color,box-shadow,background-color] hover:border-[var(--color-line-strong)] hover:bg-[var(--color-panel)] hover:shadow-[var(--shadow-panel)]',
        )}
      >
        <Search className="size-3.5 shrink-0" aria-hidden />
        <span className="flex-1 truncate">Suchen…</span>
        <kbd className="hidden shrink-0 rounded-full border border-[var(--color-line)] bg-[var(--color-panel)] px-2 py-0.5 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)] sm:inline-block">
          Ctrl K
        </kbd>
      </button>

      <div className="flex-1" />

      <TimerWidget />

      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            className="flex size-8 items-center justify-center rounded-full text-[length:var(--text-xs)] font-semibold text-white shadow-[var(--shadow-panel)] transition-opacity hover:opacity-85"
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
            className="z-50 min-w-52 rounded-[var(--radius-lg)] border border-[var(--color-line-subtle)] bg-[var(--color-panel)] p-1 shadow-[var(--shadow-popover)]"
          >
            <div className="px-2.5 py-2">
              <div className="truncate text-[length:var(--text-sm)] font-medium">
                {user?.full_name}
              </div>
              <div className="truncate text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
                {user?.email}
              </div>
            </div>
            <DropdownMenu.Separator className="my-1 h-px bg-[var(--color-line-subtle)]" />
            <DropdownMenu.Item
              onSelect={(event) => {
                // Keep the menu open: flipping the theme is something users
                // often do twice in a row to compare.
                event.preventDefault();
                setDark(!dark);
              }}
              className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-[length:var(--text-sm)] outline-none data-[highlighted]:bg-[var(--color-panel-raised)]"
            >
              {dark ? (
                <Sun className="size-3.5" aria-hidden />
              ) : (
                <Moon className="size-3.5" aria-hidden />
              )}
              {dark ? 'Helles Design' : 'Dunkles Design'}
            </DropdownMenu.Item>
            <DropdownMenu.Item
              onSelect={() => logout.mutate()}
              className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-[length:var(--text-sm)] text-[var(--color-danger)] outline-none data-[highlighted]:bg-[var(--color-danger-soft)]"
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
