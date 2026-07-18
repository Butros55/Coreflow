'use client';

import { Avatar } from '@/components/ui/avatar';
import { DataTable, Td, Th } from '@/components/ui/group-bar';
import { Panel } from '@/components/ui/panel';
import { StatusTint } from '@/components/ui/status-pill';
import type { WorkspaceRole } from '@/lib/api/types';
import { useMembers } from '@/lib/api/settings';
import { useSession } from '@/lib/session';

const ROLE_LABELS: Record<WorkspaceRole, string> = {
  owner: 'Inhaber',
  admin: 'Admin',
  member: 'Mitglied',
  readonly: 'Nur Lesen',
};

export function TeamTab() {
  const { data: session } = useSession();
  const { data: members } = useMembers(session?.workspace?.id);

  return (
    <Panel>
      <DataTable>
        <thead>
          <tr>
            <Th>Name</Th>
            <Th>E-Mail</Th>
            <Th>Rolle</Th>
            <Th>Beigetreten</Th>
          </tr>
        </thead>
        <tbody>
          {(members ?? []).map((member) => (
            <tr key={member.id} className="last:[&>td]:border-b-0">
              <Td>
                <span className="inline-flex items-center gap-2">
                  <Avatar user={member.user} size="sm" />
                  <span className="font-medium">{member.user.full_name}</span>
                </span>
              </Td>
              <Td className="text-[var(--color-ink-muted)]">{member.user.email}</Td>
              <Td>
                <StatusTint tone={member.role === 'owner' ? 'done' : 'todo'}>
                  {ROLE_LABELS[member.role]}
                </StatusTint>
              </Td>
              <Td className="text-[var(--color-ink-muted)]">
                {new Date(member.joined_at).toLocaleDateString('de-DE')}
              </Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </Panel>
  );
}
