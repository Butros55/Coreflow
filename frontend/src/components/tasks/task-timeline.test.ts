import { describe, expect, it } from 'vitest';

import { buildTimelineModel } from '@/components/tasks/task-timeline';
import type { Task } from '@/lib/api/projects';

function task(id: string, start_date: string | null, due_date: string | null): Task {
  return {
    id,
    title: id,
    project: 'p',
    project_name: 'Projekt',
    client_name: 'Kunde',
    phase: null,
    phase_name: null,
    board: 'b',
    sprint: null,
    sprint_name: null,
    parent: null,
    parent_title: null,
    description: '',
    status: 'todo',
    priority: 'medium',
    assignees: [],
    assignee_details: [],
    created_by: null,
    start_date,
    due_date,
    estimated_hours: null,
    billable: true,
    tags: [],
    order: '1024',
    story_points: null,
    progress: 0,
    archived: false,
    logged_seconds: 0,
    checklist_total: 0,
    checklist_done: 0,
    comment_count: 0,
    subtask_count: 0,
  };
}

describe('buildTimelineModel', () => {
  it('keeps undated tasks separate and pads the visible range', () => {
    const model = buildTimelineModel([
      task('A', '2026-07-10', '2026-07-12'),
      task('B', null, null),
    ]);

    expect(model).not.toBeNull();
    expect(model?.scheduled).toHaveLength(1);
    expect(model?.undated.map((item) => item.id)).toEqual(['B']);
    expect(model?.start.getDate()).toBe(9);
    expect(model?.end.getDate()).toBe(14);
  });

  it('normalises an accidentally reversed date interval', () => {
    const model = buildTimelineModel([task('A', '2026-07-20', '2026-07-10')]);

    expect(model?.scheduled[0]?.start.getDate()).toBe(10);
    expect(model?.scheduled[0]?.end.getDate()).toBe(20);
  });

  it('returns null when every task is undated', () => {
    expect(buildTimelineModel([task('A', null, null)])).toBeNull();
  });
});
