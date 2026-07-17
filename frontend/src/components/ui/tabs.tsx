'use client';

import * as TabsPrimitive from '@radix-ui/react-tabs';
import * as React from 'react';

import { cn } from '@/lib/utils';

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

/** Underline-style tab bar, matching the reference header tabs. */
export function TabsList({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        'flex scrollbar-none items-center gap-1 overflow-x-auto border-b border-[var(--color-line)]',
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        'relative -mb-px border-b-2 border-transparent px-3 py-2 text-[length:var(--text-sm)] whitespace-nowrap text-[var(--color-ink-muted)] transition-colors',
        'hover:text-[var(--color-ink)]',
        'data-[state=active]:border-[var(--color-brand)] data-[state=active]:font-medium data-[state=active]:text-[var(--color-ink)]',
        className,
      )}
      {...props}
    />
  );
}
