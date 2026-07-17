'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

export type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
};

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, invalid, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        'flex h-8 w-full rounded-[var(--radius-sm)] border bg-[var(--color-panel-sunken)] px-2.5 text-[length:var(--text-sm)] text-[var(--color-ink)]',
        'placeholder:text-[var(--color-ink-subtle)]',
        'transition-colors focus:border-[var(--color-brand)] focus:outline-none',
        'disabled:cursor-not-allowed disabled:opacity-50',
        invalid
          ? 'border-[var(--color-danger)]'
          : 'border-[var(--color-line)] hover:border-[var(--color-line-strong)]',
        className,
      )}
      {...props}
    />
  );
});

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }
>(function Textarea({ className, invalid, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        'flex min-h-[72px] w-full rounded-[var(--radius-sm)] border bg-[var(--color-panel-sunken)] px-2.5 py-2 text-[length:var(--text-sm)] text-[var(--color-ink)]',
        'placeholder:text-[var(--color-ink-subtle)]',
        'transition-colors focus:border-[var(--color-brand)] focus:outline-none',
        'disabled:cursor-not-allowed disabled:opacity-50',
        invalid
          ? 'border-[var(--color-danger)]'
          : 'border-[var(--color-line)] hover:border-[var(--color-line-strong)]',
        className,
      )}
      {...props}
    />
  );
});

export function Label({
  className,
  children,
  required,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement> & { required?: boolean }) {
  return (
    <label
      className={cn(
        'mb-1.5 block text-[length:var(--text-xs)] font-medium text-[var(--color-ink-muted)]',
        className,
      )}
      {...props}
    >
      {children}
      {required ? (
        <span className="ml-0.5 text-[var(--color-danger)]" aria-hidden>
          *
        </span>
      ) : null}
    </label>
  );
}

export function FieldError({ children }: { children?: React.ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="mt-1 text-[length:var(--text-xs)] text-[var(--color-danger)]">
      {children}
    </p>
  );
}
