'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import * as React from 'react';

import { authApi } from '@/lib/api/auth';
import { ApiError, setActiveWorkspaceId } from '@/lib/api/client';
import type { Permissions, Session } from '@/lib/api/types';

export const SESSION_QUERY_KEY = ['session'] as const;

/**
 * The session query.
 *
 * A 401 is a normal, expected state here (logged out), not a failure — so it
 * must not be retried, and it resolves to `null` rather than throwing.
 */
export function useSession() {
  return useQuery<Session | null>({
    queryKey: SESSION_QUERY_KEY,
    queryFn: async () => {
      try {
        return await authApi.session();
      } catch (error) {
        if (error instanceof ApiError && error.isUnauthenticated) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: authApi.login,
    onSuccess: (session) => {
      queryClient.setQueryData(SESSION_QUERY_KEY, session);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      // Clear everything: cached data belongs to the user who just left.
      queryClient.clear();
      router.push('/login');
    },
  });
}

export function useSwitchWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (workspaceId: string) => {
      setActiveWorkspaceId(workspaceId);
      return authApi.setDefaultWorkspace(workspaceId);
    },
    onSuccess: (session) => {
      queryClient.setQueryData(SESSION_QUERY_KEY, session);
      // Every cached list is workspace-scoped and now wrong.
      queryClient.invalidateQueries();
    },
  });
}

const DENY_ALL: Permissions = {
  can_read: false,
  can_write: false,
  can_manage_settings: false,
  can_manage_members: false,
  can_manage_integrations: false,
  can_delete_workspace: false,
};

/**
 * Capability flags for rendering.
 *
 * Defaults to deny-all while loading, so a control never flashes visible before
 * we know the role. This hides UI only — the server enforces the real rules.
 */
export function usePermissions(): Permissions {
  const { data: session } = useSession();
  return React.useMemo(
    () => ({ ...DENY_ALL, ...(session?.permissions ?? {}) }),
    [session?.permissions],
  );
}

/** Redirect to /login when the session resolves to logged-out. */
export function useRequireSession(): { session: Session | null | undefined; isLoading: boolean } {
  const router = useRouter();
  const { data: session, isLoading } = useSession();

  React.useEffect(() => {
    if (!isLoading && session === null) {
      router.replace('/login');
    }
  }, [isLoading, session, router]);

  return { session, isLoading };
}
