'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  title,
  description,
  wide = false,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
  title: string;
  description?: string;
  wide?: boolean;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="data-[state=open]:animate-in data-[state=open]:fade-in-0 fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
      <DialogPrimitive.Content
        className={cn(
          'fixed top-1/2 left-1/2 z-50 max-h-[85dvh] w-full -translate-x-1/2 -translate-y-1/2 overflow-y-auto',
          wide ? 'max-w-2xl' : 'max-w-md',
          'rounded-[var(--radius-lg)] border border-[var(--color-line-strong)] bg-[var(--color-panel)] p-5 shadow-[var(--shadow-popover)]',
          className,
        )}
        {...props}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <DialogPrimitive.Title className="text-[length:var(--text-lg)] font-semibold">
              {title}
            </DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-0.5 text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">
                {description}
              </DialogPrimitive.Description>
            ) : null}
          </div>
          <DialogPrimitive.Close
            className="rounded-[var(--radius-xs)] p-1 text-[var(--color-ink-subtle)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)]"
            aria-label="Schließen"
          >
            <X className="size-4" aria-hidden />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
