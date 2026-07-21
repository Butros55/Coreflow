'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * Tinted status pill, as in the reference designs: a pastel wash of the status
 * colour with the saturated hue reserved for the text and dot. Softer than a
 * solid fill, but the pairing still reads as one status everywhere.
 *
 * Status colour is a token lookup, never an inline hex: the same status must
 * read identically in a pill, a kanban column header, and a table row tint.
 */
export type StatusTone = 'todo' | 'progress' | 'review' | 'done' | 'stuck' | 'hold' | 'neutral';

function toneColors(tone: StatusTone): { bg: string; fg: string } {
  if (tone === 'neutral') {
    return { bg: 'var(--color-panel-raised)', fg: 'var(--color-ink-muted)' };
  }
  return { bg: `var(--color-status-${tone}-soft)`, fg: `var(--color-status-${tone})` };
}

export interface StatusPillProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: StatusTone;
  /** Fill the cell, as in the reference table view. */
  block?: boolean;
  size?: 'sm' | 'md';
}

export function StatusPill({
  tone = 'neutral',
  block = false,
  size = 'md',
  className,
  children,
  ...props
}: StatusPillProps) {
  const colors = toneColors(tone);
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-full leading-none font-medium',
        size === 'sm'
          ? 'h-5 px-2 text-[length:var(--text-2xs)]'
          : 'h-6 px-2.5 text-[length:var(--text-xs)]',
        block ? 'w-full' : '',
        className,
      )}
      style={{ backgroundColor: colors.bg, color: colors.fg }}
      {...props}
    >
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: 'currentColor' }}
        aria-hidden
      />
      {children}
    </span>
  );
}

/** Even quieter variant for inline row/column tinting. */
export function StatusTint({ tone = 'neutral', className, children, ...props }: StatusPillProps) {
  const colors = toneColors(tone);
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[length:var(--text-xs)] font-medium',
        className,
      )}
      style={{ backgroundColor: colors.bg, color: colors.fg }}
      {...props}
    >
      {children}
    </span>
  );
}

export type PriorityTone = 'low' | 'medium' | 'high' | 'urgent';

export function PriorityPill({
  tone,
  className,
  children,
  ...props
}: { tone: PriorityTone } & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center justify-center rounded-full px-2 text-[length:var(--text-2xs)] font-semibold',
        className,
      )}
      style={{
        backgroundColor: `var(--color-priority-${tone}-soft)`,
        color: `var(--color-priority-${tone})`,
      }}
      {...props}
    >
      {children}
    </span>
  );
}
