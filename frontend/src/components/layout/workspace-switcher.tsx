'use client';

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Check, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';

import { useSession, useSwitchWorkspace } from '@/lib/session';
import { cn, colorFromId, GROUP_COLORS, initialsOf } from '@/lib/utils';

export function WorkspaceSwitcher() {
  const { data: session } = useSession();
  const switchWorkspace = useSwitchWorkspace();

  const active = session?.workspace;
  const workspaces = session?.workspaces ?? [];

  if (!active) {
    return (
      <div className="flex h-9 items-center rounded-[var(--radius-sm)] px-2 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
        Kein Workspace
      </div>
    );
  }

  const handleSelect = (id: string) => {
    if (id === active.id) return;
    switchWorkspace.mutate(id, {
      onError: () => toast.error('Workspace konnte nicht gewechselt werden.'),
    });
  };

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          disabled={switchWorkspace.isPending}
          className="flex h-9 w-full items-center gap-2 rounded-[var(--radius-sm)] px-2 text-left transition-colors hover:bg-[var(--color-panel-raised)] disabled:opacity-60"
        >
          <span
            className="flex size-5 shrink-0 items-center justify-center rounded-[var(--radius-xs)] text-[length:var(--text-2xs)] font-bold text-white"
            style={{ backgroundColor: colorFromId(active.id, GROUP_COLORS) }}
            aria-hidden
          >
            {initialsOf(active.name).slice(0, 1)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[length:var(--text-sm)] font-medium">
              {active.name}
            </span>
          </span>
          <ChevronDown className="size-3.5 shrink-0 text-[var(--color-ink-subtle)]" aria-hidden />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={4}
          className="z-50 min-w-[var(--radix-dropdown-menu-trigger-width)] rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-panel-raised)] p-1 shadow-[var(--shadow-popover)]"
        >
          <DropdownMenu.Label className="px-2 py-1.5 text-[length:var(--text-2xs)] font-semibold tracking-wider text-[var(--color-ink-subtle)] uppercase">
            Workspace
          </DropdownMenu.Label>
          {workspaces.map((workspace) => (
            <DropdownMenu.Item
              key={workspace.id}
              onSelect={() => handleSelect(workspace.id)}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-[var(--radius-xs)] px-2 py-1.5 text-[length:var(--text-sm)] outline-none',
                'data-[highlighted]:bg-[var(--color-panel)] data-[highlighted]:text-[var(--color-ink)]',
              )}
            >
              <span
                className="flex size-4 shrink-0 items-center justify-center rounded-[2px] text-[9px] font-bold text-white"
                style={{ backgroundColor: colorFromId(workspace.id, GROUP_COLORS) }}
                aria-hidden
              >
                {initialsOf(workspace.name).slice(0, 1)}
              </span>
              <span className="flex-1 truncate">{workspace.name}</span>
              {workspace.id === active.id ? (
                <Check className="size-3.5 text-[var(--color-brand)]" aria-hidden />
              ) : null}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
