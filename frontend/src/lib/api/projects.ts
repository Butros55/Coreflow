import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type Paginated } from '@/lib/api/client';
import type { User } from '@/lib/api/types';

export type TaskStatus = 'todo' | 'in_progress' | 'review' | 'done' | 'stuck';
export type Priority = 'low' | 'medium' | 'high' | 'urgent';
export type ProjectStatus = 'planned' | 'active' | 'on_hold' | 'completed' | 'cancelled';

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  todo: 'Zu erledigen',
  in_progress: 'In Arbeit',
  review: 'Review',
  done: 'Erledigt',
  stuck: 'Blockiert',
};

/** Column order on every board. */
export const TASK_STATUS_ORDER: TaskStatus[] = ['todo', 'in_progress', 'review', 'done', 'stuck'];

export const PRIORITY_LABELS: Record<Priority, string> = {
  low: 'Niedrig',
  medium: 'Mittel',
  high: 'Hoch',
  urgent: 'Dringend',
};

export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  planned: 'Geplant',
  active: 'Aktiv',
  on_hold: 'Pausiert',
  completed: 'Abgeschlossen',
  cancelled: 'Abgebrochen',
};

export interface ProjectPhase {
  id: string;
  project: string;
  name: string;
  order: number;
  status: 'planned' | 'active' | 'completed';
  planned_hours: string | null;
  start_date: string | null;
  end_date: string | null;
}

export interface ProjectStats {
  open_tasks: number;
  done_tasks: number;
  logged_seconds: number;
}

export interface Project {
  id: string;
  client: string;
  client_name: string;
  name: string;
  description: string;
  status: ProjectStatus;
  priority: Priority;
  start_date: string | null;
  target_date: string | null;
  lead: User | null;
  default_hourly_rate: string | null;
  budget_hours: string | null;
  budget_amount: string | null;
  billing_model: 'hourly' | 'fixed' | 'retainer' | 'non_billable';
  progress: number;
  tags: string[];
  color: string;
  archived: boolean;
  phases: ProjectPhase[];
  stats: ProjectStats;
  default_board: string | null;
  created_at: string;
}

export interface Board {
  id: string;
  project: string;
  project_name: string;
  client_name: string;
  project_color: string;
  name: string;
  board_type: 'kanban' | 'scrum';
  default_view: 'kanban' | 'table';
}

export interface Sprint {
  id: string;
  project: string;
  board: string | null;
  name: string;
  goal: string;
  start_date: string | null;
  end_date: string | null;
  status: 'planned' | 'active' | 'completed';
  capacity_hours: string | null;
}

export interface Task {
  id: string;
  project: string;
  project_name: string;
  client_name: string;
  phase: string | null;
  phase_name: string | null;
  board: string;
  sprint: string | null;
  sprint_name: string | null;
  parent: string | null;
  title: string;
  description: string;
  status: TaskStatus;
  priority: Priority;
  assignees: string[];
  assignee_details: User[];
  created_by: string | null;
  start_date: string | null;
  due_date: string | null;
  estimated_hours: string | null;
  billable: boolean;
  tags: string[];
  order: string;
  story_points: number | null;
  progress: number;
  archived: boolean;
  logged_seconds: number;
  checklist_total: number;
  checklist_done: number;
  comment_count: number;
  subtask_count: number;
}

export interface TaskComment {
  id: string;
  task: string;
  author: User | null;
  content: string;
  created_at: string;
}

export interface ChecklistItem {
  id: string;
  task: string;
  title: string;
  done: boolean;
  order: number;
}

// ---------------------------------------------------------------------------
// Projects & boards
// ---------------------------------------------------------------------------

export function useProjects(params: { client?: string; search?: string; status?: string } = {}) {
  return useQuery({
    queryKey: ['projects', params],
    queryFn: () =>
      api.get<Paginated<Project>>('/projects/', {
        query: { ...params, page_size: 100 },
      }),
  });
}

export function useProject(id: string | null) {
  return useQuery({
    queryKey: ['project', id],
    queryFn: () => api.get<Project>(`/projects/${id}/`),
    enabled: Boolean(id),
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Project>) => api.post<Project>('/projects/', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['boards'] });
    },
  });
}

export function useBoards(params: { project?: string } = {}) {
  return useQuery({
    queryKey: ['boards', params],
    queryFn: () => api.get<Paginated<Board>>('/boards/', { query: { ...params, page_size: 100 } }),
  });
}

export function useBoard(id: string | null) {
  return useQuery({
    queryKey: ['board', id],
    queryFn: () => api.get<Board>(`/boards/${id}/`),
    enabled: Boolean(id),
  });
}

export function useSprints(projectId: string | null) {
  return useQuery({
    queryKey: ['sprints', projectId],
    queryFn: () => api.get<Paginated<Sprint>>('/sprints/', { query: { project: projectId } }),
    enabled: Boolean(projectId),
  });
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

export interface TaskListParams {
  board?: string;
  project?: string;
  client?: string;
  sprint?: string;
  status?: TaskStatus;
  assigned_to_me?: boolean;
  search?: string;
  archived?: boolean;
}

export function taskListKey(params: TaskListParams) {
  return ['tasks', params] as const;
}

export function useTasks(params: TaskListParams) {
  return useQuery({
    queryKey: taskListKey(params),
    queryFn: () =>
      api.get<Paginated<Task>>('/tasks/', {
        query: { ...params, archived: params.archived ?? false, page_size: 500 },
      }),
  });
}

export function useTask(id: string | null) {
  return useQuery({
    queryKey: ['task', id],
    queryFn: () => api.get<Task>(`/tasks/${id}/`),
    enabled: Boolean(id),
  });
}

function invalidateTaskWorld(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ['tasks'] });
  queryClient.invalidateQueries({ queryKey: ['task'] });
  queryClient.invalidateQueries({ queryKey: ['projects'] });
}

export function useCreateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Task>) => api.post<Task>('/tasks/', payload),
    onSuccess: () => invalidateTaskWorld(queryClient),
  });
}

export function useUpdateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: Partial<Task> & { id: string }) =>
      api.patch<Task>(`/tasks/${id}/`, patch),
    onSuccess: (task) => {
      queryClient.setQueryData(['task', task.id], task);
      invalidateTaskWorld(queryClient);
    },
  });
}

export interface MoveTaskInput {
  taskId: string;
  status: TaskStatus;
  /** Task id the moved task should come AFTER in the target column; null = top. */
  after: string | null;
  /** The board list this move affects, for the optimistic cache update. */
  listParams: TaskListParams;
}

/**
 * Kanban move with an optimistic cache update: the card lands visually where it
 * was dropped immediately; the server response then settles the true order.
 */
export function useMoveTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, status, after }: MoveTaskInput) =>
      api.post<Task>(`/tasks/${taskId}/move/`, { status, after }),
    onMutate: async ({ taskId, status, after, listParams }) => {
      const key = taskListKey(listParams);
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<Paginated<Task>>(key);
      if (previous) {
        const tasks = [...previous.results];
        const moving = tasks.find((t) => t.id === taskId);
        if (moving) {
          const without = tasks.filter((t) => t.id !== taskId);
          const updated: Task = { ...moving, status };
          // Rebuild in visual order: target column sorted by order, insert after anchor.
          const column = without
            .filter((t) => t.status === status)
            .sort((a, b) => Number(a.order) - Number(b.order));
          const index = after ? column.findIndex((t) => t.id === after) + 1 : 0;
          column.splice(index, 0, updated);
          // Re-derive fake orders inside the column so sorts stay stable until refetch.
          const reordered = column.map((t, i) => ({ ...t, order: String((i + 1) * 1024) }));
          const rest = without.filter((t) => t.status !== status);
          queryClient.setQueryData<Paginated<Task>>(key, {
            ...previous,
            results: [...rest, ...reordered],
          });
        }
      }
      return { previous, key };
    },
    onError: (_error, _input, context) => {
      if (context?.previous) queryClient.setQueryData(context.key, context.previous);
    },
    onSettled: () => invalidateTaskWorld(queryClient),
  });
}

// ---------------------------------------------------------------------------
// Comments & checklist
// ---------------------------------------------------------------------------

export function useTaskComments(taskId: string | null) {
  return useQuery({
    queryKey: ['task-comments', taskId],
    queryFn: () => api.get<Paginated<TaskComment>>('/task-comments/', { query: { task: taskId } }),
    enabled: Boolean(taskId),
  });
}

export function useAddComment(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: string) =>
      api.post<TaskComment>('/task-comments/', { task: taskId, content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task-comments', taskId] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}

export function useChecklist(taskId: string | null) {
  return useQuery({
    queryKey: ['task-checklist', taskId],
    queryFn: () =>
      api.get<Paginated<ChecklistItem>>('/task-checklist/', { query: { task: taskId } }),
    enabled: Boolean(taskId),
  });
}

export function useChecklistMutations(taskId: string) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['task-checklist', taskId] });
    queryClient.invalidateQueries({ queryKey: ['tasks'] });
  };
  const add = useMutation({
    mutationFn: (title: string) =>
      api.post<ChecklistItem>('/task-checklist/', { task: taskId, title }),
    onSuccess: invalidate,
  });
  const toggle = useMutation({
    mutationFn: (item: ChecklistItem) =>
      api.patch<ChecklistItem>(`/task-checklist/${item.id}/`, { done: !item.done }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`/task-checklist/${id}/`),
    onSuccess: invalidate,
  });
  return { add, toggle, remove };
}
