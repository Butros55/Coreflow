'use client';

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { CheckSquare, MessageSquare } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { STATUS_TONES } from '@/components/tasks/status-select';
import { AvatarStack } from '@/components/ui/avatar';
import { PriorityPill } from '@/components/ui/status-pill';
import {
  PRIORITY_LABELS,
  TASK_STATUS_LABELS,
  TASK_STATUS_ORDER,
  useMoveTask,
  type Task,
  type TaskListParams,
  type TaskStatus,
} from '@/lib/api/projects';
import { cn } from '@/lib/utils';

interface KanbanProps {
  tasks: Task[];
  listParams: TaskListParams;
  onOpenTask: (taskId: string) => void;
  canEdit: boolean;
}

function columnOf(tasks: Task[], status: TaskStatus): Task[] {
  return tasks
    .filter((task) => task.status === status)
    .sort((a, b) => Number(a.order) - Number(b.order));
}

export function KanbanBoard({ tasks, listParams, onOpenTask, canEdit }: KanbanProps) {
  const moveTask = useMoveTask();
  const [activeTask, setActiveTask] = React.useState<Task | null>(null);

  // A small activation distance keeps plain clicks working as "open drawer".
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  const columns = React.useMemo(
    () => TASK_STATUS_ORDER.map((status) => ({ status, items: columnOf(tasks, status) })),
    [tasks],
  );

  const handleDragStart = (event: DragStartEvent) => {
    const task = tasks.find((t) => t.id === event.active.id);
    setActiveTask(task ?? null);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveTask(null);
    const { active, over } = event;
    if (!over) return;
    const task = tasks.find((t) => t.id === active.id);
    if (!task) return;

    const overData = over.data.current as
      | { type: 'column'; status: TaskStatus }
      | { type: 'card'; status: TaskStatus; taskId: string }
      | undefined;
    if (!overData) return;

    const targetStatus = overData.status;
    const column = columnOf(tasks, targetStatus).filter((t) => t.id !== task.id);

    // Dropping on a card inserts BEFORE it; dropping on the column appends.
    let after: string | null;
    if (overData.type === 'card') {
      const index = column.findIndex((t) => t.id === overData.taskId);
      after = index <= 0 ? null : (column[index - 1]?.id ?? null);
    } else {
      after = column.length > 0 ? (column[column.length - 1]?.id ?? null) : null;
    }

    if (task.status === targetStatus) {
      // No-op drop back onto its own position.
      const currentIndex = columnOf(tasks, targetStatus).findIndex((t) => t.id === task.id);
      const anchorId =
        currentIndex <= 0 ? null : columnOf(tasks, targetStatus)[currentIndex - 1]?.id;
      if ((anchorId ?? null) === after) return;
    }

    moveTask.mutate(
      { taskId: task.id, status: targetStatus, after, listParams },
      { onError: () => toast.error('Verschieben fehlgeschlagen.') },
    );
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setActiveTask(null)}
    >
      <div className="flex h-full gap-3 overflow-x-auto pb-4">
        {columns.map(({ status, items }) => (
          <KanbanColumn
            key={status}
            status={status}
            tasks={items}
            onOpenTask={onOpenTask}
            canEdit={canEdit}
          />
        ))}
      </div>
      <DragOverlay dropAnimation={null}>
        {activeTask ? <KanbanCard task={activeTask} overlay /> : null}
      </DragOverlay>
    </DndContext>
  );
}

function KanbanColumn({
  status,
  tasks,
  onOpenTask,
  canEdit,
}: {
  status: TaskStatus;
  tasks: Task[];
  onOpenTask: (taskId: string) => void;
  canEdit: boolean;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${status}`,
    data: { type: 'column', status },
    disabled: !canEdit,
  });

  const color = `var(--color-status-${STATUS_TONES[status]})`;

  return (
    <div className="flex w-72 shrink-0 flex-col">
      {/* Saturated column header, as in the reference. */}
      <div
        className="mb-2 flex h-7 items-center justify-center rounded-[var(--radius-sm)] text-[length:var(--text-xs)] font-semibold text-[#0b1220]"
        style={{ backgroundColor: color }}
      >
        {TASK_STATUS_LABELS[status]}/{tasks.length}
      </div>
      <div
        ref={setNodeRef}
        className={cn(
          'flex min-h-32 flex-1 flex-col gap-2 rounded-[var(--radius-md)] p-1 transition-colors',
          isOver && 'bg-[var(--color-brand-subtle)]',
        )}
      >
        {tasks.map((task) => (
          <DraggableCard
            key={task.id}
            task={task}
            onOpen={() => onOpenTask(task.id)}
            canEdit={canEdit}
          />
        ))}
      </div>
    </div>
  );
}

function DraggableCard({
  task,
  onOpen,
  canEdit,
}: {
  task: Task;
  onOpen: () => void;
  canEdit: boolean;
}) {
  const { setNodeRef, attributes, listeners, isDragging } = useDraggable({
    id: task.id,
    data: { type: 'card', status: task.status, taskId: task.id },
    disabled: !canEdit,
  });
  // Cards are drop targets too, so a drop can land BETWEEN cards.
  const { setNodeRef: setDropRef } = useDroppable({
    id: `card-drop-${task.id}`,
    data: { type: 'card', status: task.status, taskId: task.id },
    disabled: !canEdit,
  });

  return (
    <div ref={setDropRef}>
      <div
        ref={setNodeRef}
        {...attributes}
        {...listeners}
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onOpen();
          }
        }}
        className={cn(isDragging && 'opacity-40')}
      >
        <KanbanCard task={task} />
      </div>
    </div>
  );
}

export function KanbanCard({ task, overlay = false }: { task: Task; overlay?: boolean }) {
  return (
    <div
      className={cn(
        'cursor-pointer rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-panel)] p-3 transition-colors',
        overlay
          ? 'shadow-[var(--shadow-popover)] ring-1 ring-[var(--color-brand)]'
          : 'hover:border-[var(--color-line-strong)]',
      )}
    >
      <div className="mb-2 text-[length:var(--text-sm)] leading-snug font-medium">{task.title}</div>
      <div className="flex flex-wrap items-center gap-1.5">
        <PriorityPill tone={task.priority}>{PRIORITY_LABELS[task.priority]}</PriorityPill>
        {task.story_points != null ? (
          <span className="rounded-[var(--radius-xs)] bg-[var(--color-panel-raised)] px-1.5 py-0.5 text-[length:var(--text-2xs)] text-[var(--color-ink-muted)]">
            {task.story_points} SP
          </span>
        ) : null}
        <span className="flex-1" />
        {task.checklist_total > 0 ? (
          <span className="inline-flex items-center gap-1 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            <CheckSquare className="size-3" aria-hidden />
            {task.checklist_done}/{task.checklist_total}
          </span>
        ) : null}
        {task.comment_count > 0 ? (
          <span className="inline-flex items-center gap-1 text-[length:var(--text-2xs)] text-[var(--color-ink-subtle)]">
            <MessageSquare className="size-3" aria-hidden />
            {task.comment_count}
          </span>
        ) : null}
        <AvatarStack users={task.assignee_details} size="sm" />
      </div>
      {task.due_date ? (
        <div
          className={cn(
            'mt-2 text-[length:var(--text-2xs)]',
            new Date(task.due_date) < new Date() && task.status !== 'done'
              ? 'font-medium text-[var(--color-danger)]'
              : 'text-[var(--color-ink-subtle)]',
          )}
        >
          Fällig {new Date(task.due_date).toLocaleDateString('de-DE')}
        </div>
      ) : null}
    </div>
  );
}
