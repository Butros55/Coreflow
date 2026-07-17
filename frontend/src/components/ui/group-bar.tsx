import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * The coloured group header from the reference tables: a saturated bar on the
 * left, group title, count — with the rows box indented under it.
 */
export function GroupSection({
  color,
  title,
  count,
  children,
  meta,
  className,
}: {
  color: string;
  title: string;
  count?: number;
  meta?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn('mb-5', className)}>
      <div className="mb-1.5 flex items-center gap-2">
        <span
          className="h-5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
          aria-hidden
        />
        <h3 className="text-[length:var(--text-sm)] font-semibold" style={{ color }}>
          {title}
        </h3>
        {count !== undefined ? (
          <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">
            {count}
          </span>
        ) : null}
        <span className="flex-1" />
        {meta}
      </div>
      <div
        className="overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-line)]"
        style={{ borderLeftColor: color, borderLeftWidth: 3 }}
      >
        {children}
      </div>
    </section>
  );
}

/** Dense table primitives shared by the list views. */
export function DataTable({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse bg-[var(--color-panel)] text-[length:var(--text-sm)]">
        {children}
      </table>
    </div>
  );
}

export function Th({
  className,
  children,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'border-b border-[var(--color-line)] bg-[var(--color-panel-sunken)] px-3 py-2 text-left text-[length:var(--text-2xs)] font-semibold tracking-wider whitespace-nowrap text-[var(--color-ink-subtle)] uppercase',
        className,
      )}
      {...props}
    >
      {children}
    </th>
  );
}

export function Td({
  className,
  children,
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn(
        'border-b border-[var(--color-line-subtle)] px-3 py-1.5 align-middle',
        className,
      )}
      {...props}
    >
      {children}
    </td>
  );
}

export function ClickableRow({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        'cursor-pointer transition-colors hover:bg-[var(--color-panel-raised)] last:[&>td]:border-b-0',
        className,
      )}
      {...props}
    >
      {children}
    </tr>
  );
}
