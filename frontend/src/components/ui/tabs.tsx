'use client';

import * as TabsPrimitive from '@radix-ui/react-tabs';
import * as React from 'react';

import { cn } from '@/lib/utils';

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

/**
 * Segmented pill tab bar, matching the reference designs: triggers sit in a
 * sunken rounded track, the active one floats on a raised white pill.
 */
export function TabsList({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        'inline-flex max-w-full scrollbar-none items-center gap-1 overflow-x-auto rounded-full bg-[var(--color-panel-sunken)] p-1',
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
        'rounded-full px-3.5 py-1.5 text-[length:var(--text-sm)] whitespace-nowrap text-[var(--color-ink-muted)] transition-colors',
        'hover:text-[var(--color-ink)]',
        'data-[state=active]:bg-[var(--color-panel)] data-[state=active]:font-medium data-[state=active]:text-[var(--color-ink)] data-[state=active]:shadow-[var(--shadow-panel)]',
        className,
      )}
      {...props}
    />
  );
}
