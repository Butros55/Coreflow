'use client';

import { SquareKanban } from 'lucide-react';
import Link from 'next/link';

import { PageHeader } from '@/components/layout/app-shell';
import { EmptyState, Panel } from '@/components/ui/panel';
import { useBoards } from '@/lib/api/projects';

export default function BoardsPage() {
  const { data, isLoading } = useBoards();
  const boards = data?.results ?? [];

  return (
    <>
      <PageHeader title="Boards" description="Alle Projektboards" />
      <div className="p-5">
        {isLoading ? (
          <p className="text-[length:var(--text-sm)] text-[var(--color-ink-muted)]">Lädt…</p>
        ) : boards.length === 0 ? (
          <EmptyState
            icon={<SquareKanban className="size-8" aria-hidden />}
            title="Keine Boards"
            description="Boards entstehen automatisch mit jedem Projekt."
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {boards.map((board) => (
              <Link key={board.id} href={`/boards/${board.id}`}>
                <Panel className="p-4 transition-colors hover:border-[var(--color-line-strong)]">
                  <div className="flex items-center gap-2">
                    <span
                      className="size-2.5 rounded-full"
                      style={{ backgroundColor: board.project_color || 'var(--color-brand)' }}
                      aria-hidden
                    />
                    <span className="font-medium">{board.project_name}</span>
                  </div>
                  <div className="mt-1 text-[length:var(--text-xs)] text-[var(--color-ink-muted)]">
                    {board.client_name} · {board.name}
                    {board.board_type === 'scrum' ? ' · Scrum' : ''}
                  </div>
                </Panel>
              </Link>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
