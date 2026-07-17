'use client';

import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { Loader2 } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-sm)] font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary:
          'bg-[var(--color-brand)] text-white hover:bg-[var(--color-brand-hover)] active:bg-[var(--color-brand-active)]',
        secondary:
          'bg-[var(--color-panel-raised)] text-[var(--color-ink)] border border-[var(--color-line)] hover:border-[var(--color-line-strong)] hover:bg-[var(--color-panel)]',
        ghost:
          'text-[var(--color-ink-muted)] hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)]',
        danger: 'bg-[var(--color-danger)] text-white hover:brightness-110',
        outline:
          'border border-[var(--color-line-strong)] text-[var(--color-ink)] hover:bg-[var(--color-panel-raised)]',
        link: 'text-[var(--color-brand)] underline-offset-4 hover:underline',
      },
      size: {
        xs: 'h-6 px-2 text-[length:var(--text-2xs)] [&_svg]:size-3',
        sm: 'h-7 px-2.5 text-[length:var(--text-xs)] [&_svg]:size-3.5',
        md: 'h-8 px-3 text-[length:var(--text-sm)] [&_svg]:size-4',
        lg: 'h-10 px-4 text-[length:var(--text-base)] [&_svg]:size-4',
        icon: 'h-8 w-8 [&_svg]:size-4',
        'icon-sm': 'h-7 w-7 [&_svg]:size-3.5',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild = false, loading = false, children, disabled, ...props },
  ref,
) {
  const classes = cn(buttonVariants({ variant, size }), className);

  // Radix `Slot` merges props onto its child and requires EXACTLY ONE React
  // element child. Rendering `{spinner-or-null}{children}` alongside it yields
  // two children (`[null, <Link/>]`) and throws at runtime — so the asChild
  // branch must return children untouched, with no sibling. A spinner is
  // therefore only supported on a real <button>; `asChild` delegates rendering
  // to the caller's element entirely.
  if (asChild) {
    return (
      <Slot ref={ref} className={classes} {...props}>
        {children}
      </Slot>
    );
  }

  return (
    <button
      ref={ref}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Loader2 className="animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
});

export { buttonVariants };
