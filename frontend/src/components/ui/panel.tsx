import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * The floating card that everything sits in: large radius, soft layered
 * shadow, and only a whisper of a border so cards still separate on the
 * sunken surfaces where the shadow alone would vanish.
 */
export function Panel({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'rounded-[var(--radius-xl)] border border-[var(--color-line-subtle)] bg-[var(--color-panel)] shadow-[var(--shadow-panel)]',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function PanelHeader({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-3 border-b border-[var(--color-line-subtle)] px-4 py-3',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function PanelTitle({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn(
        'text-[length:var(--text-base)] font-semibold text-[var(--color-ink)]',
        className,
      )}
      {...props}
    >
      {children}
    </h2>
  );
}

export function PanelBody({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('p-4', className)} {...props}>
      {children}
    </div>
  );
}

/**
 * KPI tile used across the client and finance dashboards.
 *
 * `value` is pre-formatted by the caller — formatting money needs the currency
 * and locale, which this component has no business knowing. The optional
 * `icon` renders in a tinted circular chip, as in the reference dashboards.
 */
export function StatTile({
  label,
  value,
  hint,
  icon,
  tone = 'default',
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: 'default' | 'success' | 'warning' | 'danger';
  className?: string;
}) {
  const toneColor = {
    default: 'var(--color-ink)',
    success: 'var(--color-success)',
    warning: 'var(--color-warning)',
    danger: 'var(--color-danger)',
  }[tone];

  const chipColors = {
    default: { bg: 'var(--color-brand-subtle)', fg: 'var(--color-brand)' },
    success: { bg: 'var(--color-success-soft)', fg: 'var(--color-success)' },
    warning: { bg: 'var(--color-warning-soft)', fg: 'var(--color-warning)' },
    danger: { bg: 'var(--color-danger-soft)', fg: 'var(--color-danger)' },
  }[tone];

  return (
    <div
      className={cn(
        'flex items-center gap-3.5 rounded-[var(--radius-xl)] border border-[var(--color-line-subtle)] bg-[var(--color-panel)] px-4 py-3.5 shadow-[var(--shadow-panel)]',
        className,
      )}
    >
      {icon ? (
        <div
          className="flex size-10 shrink-0 items-center justify-center rounded-full [&_svg]:size-4.5"
          style={{ backgroundColor: chipColors.bg, color: chipColors.fg }}
          aria-hidden
        >
          {icon}
        </div>
      ) : null}
      <div className="min-w-0">
        <div className="text-[length:var(--text-xs)] font-medium text-[var(--color-ink-muted)]">
          {label}
        </div>
        <div
          className="tabular mt-1 text-[length:var(--text-2xl)] leading-tight font-semibold"
          style={{ color: toneColor }}
        >
          {value}
        </div>
        {hint ? (
          <div className="mt-0.5 text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-[var(--radius-xl)] border border-dashed border-[var(--color-line-strong)] bg-[var(--color-panel-sunken)] px-6 py-10 text-center',
        className,
      )}
    >
      {icon ? <div className="text-[var(--color-ink-subtle)]">{icon}</div> : null}
      <div className="text-[length:var(--text-base)] font-medium text-[var(--color-ink)]">
        {title}
      </div>
      {description ? (
        <p className="max-w-sm text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
