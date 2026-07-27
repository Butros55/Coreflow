import { api, setActiveWorkspaceId } from '@/lib/api/client';
import type { LoginPayload, Session, User } from '@/lib/api/types';

export const authApi = {
  /** Session bootstrap. `skipWorkspace` on login: no workspace is chosen yet. */
  session: () => api.get<Session>('/auth/session'),

  login: async (payload: LoginPayload): Promise<Session> => {
    const session = await api.post<Session>('/auth/login', payload, { skipWorkspace: true });
    setActiveWorkspaceId(session.workspace?.id ?? null);
    return session;
  },

  logout: async (): Promise<void> => {
    await api.post<void>('/auth/logout');
    setActiveWorkspaceId(null);
  },

  changePassword: (currentPassword: string, newPassword: string) =>
    api.post<void>('/auth/password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),

  updateProfile: (
    patch: Partial<Pick<User, 'first_name' | 'last_name' | 'time_zone' | 'locale'>>,
  ) => api.patch<User>('/auth/me', patch),

  setDefaultWorkspace: (workspaceId: string) =>
    // Trailing slash is load-bearing: the router registers set-default/ and
    // APPEND_SLASH cannot redirect a POST — without it this 500s.
    api.post<Session>(`/workspaces/${workspaceId}/set-default/`),

  createWorkspace: (payload: { name: string; small_business?: boolean }) =>
    // skipWorkspace: the caller may not have any workspace yet (onboarding).
    api.post<{ id: string; name: string }>('/workspaces/', payload, { skipWorkspace: true }),
};
