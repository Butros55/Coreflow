import type { User } from '@/lib/api/types';
import { cn, colorFromId, GROUP_COLORS } from '@/lib/utils';

export function Avatar({
  user,
  size = 'md',
  className,
}: {
  user: Pick<User, 'id' | 'initials' | 'full_name' | 'avatar_color'>;
  size?: 'sm' | 'md';
  className?: string;
}) {
  return (
    <span
      title={user.full_name}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white',
        size === 'sm' ? 'size-5 text-[9px]' : 'size-6 text-[10px]',
        className,
      )}
      style={{ backgroundColor: user.avatar_color || colorFromId(user.id, GROUP_COLORS) }}
    >
      {user.initials}
    </span>
  );
}

/** Overlapping avatar stack, as in the reference tables. */
export function AvatarStack({
  users,
  max = 3,
  size = 'md',
}: {
  users: Pick<User, 'id' | 'initials' | 'full_name' | 'avatar_color'>[];
  max?: number;
  size?: 'sm' | 'md';
}) {
  if (users.length === 0) {
    return <span className="text-[length:var(--text-xs)] text-[var(--color-ink-subtle)]">—</span>;
  }
  const visible = users.slice(0, max);
  const overflow = users.length - visible.length;
  return (
    <span className="inline-flex items-center">
      {visible.map((user, index) => (
        <span key={user.id} className={index > 0 ? '-ml-1.5' : ''}>
          <Avatar user={user} size={size} className="ring-2 ring-[var(--color-panel)]" />
        </span>
      ))}
      {overflow > 0 ? (
        <span
          className={cn(
            '-ml-1.5 inline-flex items-center justify-center rounded-full bg-[var(--color-panel-raised)] font-medium text-[var(--color-ink-muted)] ring-2 ring-[var(--color-panel)]',
            size === 'sm' ? 'size-5 text-[9px]' : 'size-6 text-[10px]',
          )}
        >
          +{overflow}
        </span>
      ) : null}
    </span>
  );
}
