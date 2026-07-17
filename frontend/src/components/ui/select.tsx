'use client';

import { ChevronDown } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * Styled native <select>. Native on purpose: forms get keyboard support,
 * mobile pickers and screen-reader semantics for free, which a custom listbox
 * has to re-earn.
 */
export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }
>(function Select({ className, invalid, children, ...props }, ref) {
  return (
    <div className="relative">
      <select
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          'h-8 w-full appearance-none rounded-[var(--radius-sm)] border bg-[var(--color-panel-sunken)] pr-8 pl-2.5 text-[length:var(--text-sm)] text-[var(--color-ink)]',
          'transition-colors focus:border-[var(--color-brand)] focus:outline-none',
          'disabled:cursor-not-allowed disabled:opacity-50',
          invalid
            ? 'border-[var(--color-danger)]'
            : 'border-[var(--color-line)] hover:border-[var(--color-line-strong)]',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute top-1/2 right-2 size-3.5 -translate-y-1/2 text-[var(--color-ink-subtle)]"
        aria-hidden
      />
    </div>
  );
});
