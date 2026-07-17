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
    api.post<Session>(`/workspaces/${workspaceId}/set-default`),
};
