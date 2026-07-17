'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * The saturated status pill from the reference design.
 *
 * Status colour is a token lookup, never an inline hex: the same status must
 * read identically in a pill, a kanban column header, and a table row tint.
 */
export type StatusTone = 'todo' | 'progress' | 'review' | 'done' | 'stuck' | 'hold' | 'neutral';

const TONE_STYLES: Record<StatusTone, { bg: string; fg: string }> = {
  todo: { bg: 'var(--color-status-todo)', fg: '#04122b' },
  progress: { bg: 'var(--color-status-progress)', fg: '#2a1a00' },
  review: { bg: 'var(--color-status-review)', fg: '#1e0733' },
  done: { bg: 'var(--color-status-done)', fg: '#03210f' },
  stuck: { bg: 'var(--color-status-stuck)', fg: '#2b0505' },
  hold: { bg: 'var(--color-status-hold)', fg: '#0b1220' },
  neutral: { bg: 'var(--color-panel-raised)', fg: 'var(--color-ink-muted)' },
};

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
  const style = TONE_STYLES[tone];
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-[var(--radius-xs)] leading-none font-medium',
        size === 'sm'
          ? 'h-5 px-2 text-[length:var(--text-2xs)]'
          : 'h-6 px-2.5 text-[length:var(--text-xs)]',
        block ? 'w-full' : '',
        className,
      )}
      style={{ backgroundColor: style.bg, color: style.fg }}
      {...props}
    >
      {children}
    </span>
  );
}

/** Low-alpha variant for tinting rows/columns without shouting. */
export function StatusTint({ tone = 'neutral', className, children, ...props }: StatusPillProps) {
  const soft =
    tone === 'neutral' ? 'var(--color-panel-raised)' : `var(--color-status-${tone}-soft)`;
  const solid = tone === 'neutral' ? 'var(--color-ink-muted)' : `var(--color-status-${tone})`;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[var(--radius-xs)] px-2 py-0.5 text-[length:var(--text-xs)] font-medium',
        className,
      )}
      style={{ backgroundColor: soft, color: solid }}
      {...props}
    >
      {children}
    </span>
  );
}

export type PriorityTone = 'low' | 'medium' | 'high' | 'urgent';

const PRIORITY_STYLES: Record<PriorityTone, string> = {
  low: 'var(--color-priority-low)',
  medium: 'var(--color-priority-medium)',
  high: 'var(--color-priority-high)',
  urgent: 'var(--color-priority-urgent)',
};

export function PriorityPill({
  tone,
  className,
  children,
  ...props
}: { tone: PriorityTone } & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center justify-center rounded-[var(--radius-xs)] px-2.5 text-[length:var(--text-xs)] font-medium text-white',
        className,
      )}
      style={{ backgroundColor: PRIORITY_STYLES[tone] }}
      {...props}
    >
      {children}
    </span>
  );
}
