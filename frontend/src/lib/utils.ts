import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Merge class names, letting later Tailwind utilities win over earlier ones. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Format a Decimal-as-string money value.
 *
 * The API sends money as a string precisely so it never round-trips through a
 * float. Number() here is for *display only* — never feed the result back into
 * arithmetic that the server will trust.
 */
export function formatMoney(
  value: string | number | null | undefined,
  currency = 'EUR',
  locale = 'de-DE',
): string {
  if (value === null || value === undefined || value === '') return '—';
  const amount = typeof value === 'string' ? Number.parseFloat(value) : value;
  if (Number.isNaN(amount)) return '—';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

/** Format hours (e.g. 7.5 → "7,50 h"). */
export function formatHours(value: string | number | null | undefined, locale = 'de-DE'): string {
  if (value === null || value === undefined || value === '') return '—';
  const hours = typeof value === 'string' ? Number.parseFloat(value) : value;
  if (Number.isNaN(hours)) return '—';
  return `${new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(hours)} h`;
}

/** Seconds → "1:23:45" / "23:45". Used by the running timer. */
export function formatDuration(totalSeconds: number, withSeconds = true): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  const pad = (n: number) => n.toString().padStart(2, '0');
  if (!withSeconds) return `${hours}:${pad(minutes)}`;
  return `${hours}:${pad(minutes)}:${pad(seconds)}`;
}

export function initialsOf(name: string | null | undefined, fallback = '??'): string {
  if (!name?.trim()) return fallback;
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return (parts[0] ?? '').slice(0, 2).toUpperCase();
  return `${parts[0]?.[0] ?? ''}${parts[parts.length - 1]?.[0] ?? ''}`.toUpperCase();
}

/**
 * Deterministic colour for an entity, so the same client always gets the same
 * avatar tint across sessions and devices.
 */
export function colorFromId(id: string, palette: readonly string[]): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash << 5) - hash + id.charCodeAt(i);
    hash |= 0;
  }
  const index = Math.abs(hash) % palette.length;
  return palette[index] ?? palette[0] ?? '#4f7dff';
}

export const GROUP_COLORS = [
  'var(--color-group-1)',
  'var(--color-group-2)',
  'var(--color-group-3)',
  'var(--color-group-4)',
  'var(--color-group-5)',
  'var(--color-group-6)',
  'var(--color-group-7)',
  'var(--color-group-8)',
] as const;
