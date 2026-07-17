'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as React from 'react';
import { Toaster } from 'sonner';

import { ApiError } from '@/lib/api/client';

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // Retrying an auth or permission failure just burns requests and, on
          // a throttled endpoint, makes things worse. Only retry transient ones.
          if (error instanceof ApiError) {
            if (error.status >= 400 && error.status < 500 && error.status !== 429) return false;
          }
          return failureCount < 2;
        },
      },
      mutations: {
        // Never auto-retry a mutation: a retried POST can double-create.
        retry: false,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

function getQueryClient(): QueryClient {
  if (typeof window === 'undefined') {
    // Server: a fresh client per request, so no data leaks between users.
    return makeQueryClient();
  }
  // Browser: one singleton, or React would discard the cache on every suspense.
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: {
            background: 'var(--color-panel-raised)',
            border: '1px solid var(--color-line)',
            color: 'var(--color-ink)',
          },
        }}
      />
    </QueryClientProvider>
  );
}
