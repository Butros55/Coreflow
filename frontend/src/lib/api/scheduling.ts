import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, API_BASE, type Paginated } from '@/lib/api/client';
import type { User } from '@/lib/api/types';

export type AppointmentStatus = 'planned' | 'confirmed' | 'done' | 'cancelled';

export const APPOINTMENT_STATUS_LABELS: Record<AppointmentStatus, string> = {
  planned: 'Geplant',
  confirmed: 'Bestätigt',
  done: 'Erledigt',
  cancelled: 'Abgesagt',
};

export interface Appointment {
  id: string;
  client: string | null;
  client_name: string | null;
  project: string | null;
  project_name: string | null;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string;
  location: string;
  video_link: string;
  participants: string[];
  participant_details: User[];
  status: AppointmentStatus;
  status_display: string;
  reminder_minutes_before: number | null;
  outcome_notes: string;
  next_steps: string;
  created_at: string;
}

export function useAppointments(
  params: { from_date?: string; to_date?: string; client?: string } = {},
) {
  return useQuery({
    queryKey: ['appointments', params],
    queryFn: () =>
      api.get<Paginated<Appointment>>('/appointments/', {
        query: { ...params, page_size: 200 },
      }),
  });
}

export interface AppointmentPayload {
  title: string;
  description?: string;
  starts_at: string;
  ends_at: string;
  location?: string;
  video_link?: string;
  client?: string | null;
  project?: string | null;
  status?: AppointmentStatus;
  next_steps?: string;
  outcome_notes?: string;
}

function invalidate(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ['appointments'] });
}

export function useSaveAppointment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AppointmentPayload & { id?: string }) =>
      payload.id
        ? api.patch<Appointment>(`/appointments/${payload.id}/`, payload)
        : api.post<Appointment>('/appointments/', payload),
    onSuccess: () => invalidate(queryClient),
  });
}

export function useDeleteAppointment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/appointments/${id}/`),
    onSuccess: () => invalidate(queryClient),
  });
}

export function useCreateTaskFromAppointment() {
  return useMutation({
    mutationFn: (id: string) =>
      api.post<{ task_id: string; board_id: string }>(`/appointments/${id}/create-task/`),
  });
}

/** The ICS export URL (a GET that streams a file). */
export function appointmentsIcsUrl(): string {
  return `${API_BASE}/appointments/export.ics`;
}
