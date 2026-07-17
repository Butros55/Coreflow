'use client';

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Check } from 'lucide-react';
import { toast } from 'sonner';

import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import {
  TASK_STATUS_LABELS,
  TASK_STATUS_ORDER,
  useUpdateTask,
  type TaskStatus,
} from '@/lib/api/projects';

/** One source of truth for status → colour across pills, columns and tints. */
export const STATUS_TONES: Record<TaskStatus, StatusTone> = {
  todo: 'todo',
  in_progress: 'progress',
  review: 'review',
  done: 'done',
  stuck: 'stuck',
};

/**
 * The signature interaction of the reference design: click the status pill,
 * pick a status, the row updates in place.
 */
export function StatusSelect({
  taskId,
  status,
  block = true,
  disabled = false,
}: {
  taskId: string;
  status: TaskStatus;
  block?: boolean;
  disabled?: boolean;
}) {
  const updateTask = useUpdateTask();

  if (disabled) {
    return (
      <StatusPill tone={STATUS_TONES[status]} block={block}>
        {TASK_STATUS_LABELS[status]}
      </StatusPill>
    );
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="w-full cursor-pointer transition-opacity hover:opacity-85"
          aria-label={`Status ändern (aktuell: ${TASK_STATUS_LABELS[status]})`}
          onClick={(event) => event.stopPropagation()}
        >
          <StatusPill tone={STATUS_TONES[status]} block={block}>
            {TASK_STATUS_LABELS[status]}
          </StatusPill>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={4}
          className="z-50 min-w-44 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-panel-raised)] p-1 shadow-[var(--shadow-popover)]"
        >
          {TASK_STATUS_ORDER.map((value) => (
            <DropdownMenu.Item
              key={value}
              onSelect={() => {
                if (value === status) return;
                updateTask.mutate(
                  { id: taskId, status: value },
                  { onError: () => toast.error('Status konnte nicht geändert werden.') },
                );
              }}
              className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-xs)] px-2 py-1.5 outline-none data-[highlighted]:bg-[var(--color-panel)]"
            >
              <StatusPill tone={STATUS_TONES[value]} size="sm">
                {TASK_STATUS_LABELS[value]}
              </StatusPill>
              <span className="flex-1" />
              {value === status ? (
                <Check className="size-3.5 text-[var(--color-brand)]" aria-hidden />
              ) : null}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
