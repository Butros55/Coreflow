import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, API_BASE, type Paginated } from '@/lib/api/client';
import type { User } from '@/lib/api/types';

export interface StoredFile {
  id: string;
  client: string | null;
  project: string | null;
  task: string | null;
  filename: string;
  content_type: string;
  size_bytes: number;
  size_display: string;
  description: string;
  uploaded_by: User | null;
  is_generated: boolean;
  download_url: string | null;
  created_at: string;
}

export function useFiles(params: { client?: string; project?: string; search?: string } = {}) {
  return useQuery({
    queryKey: ['files', params],
    queryFn: () =>
      api.get<Paginated<StoredFile>>('/files/', { query: { ...params, page_size: 100 } }),
  });
}

export function useUploadFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      file: File;
      client?: string;
      project?: string;
      description?: string;
    }) => {
      const form = new FormData();
      form.append('file', input.file);
      if (input.client) form.append('client', input.client);
      if (input.project) form.append('project', input.project);
      if (input.description) form.append('description', input.description);
      return api.post<StoredFile>('/files/', form);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['files'] }),
  });
}

export function useDeleteFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/files/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['files'] }),
  });
}

export function fileDownloadUrl(id: string): string {
  return `${API_BASE}/files/${id}/download/`;
}
