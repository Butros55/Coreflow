import { describe, expect, it } from 'vitest';

import { colorFromId, formatDuration, formatHours, formatMoney, initialsOf } from '@/lib/utils';

describe('formatMoney', () => {
  it('formats a Decimal string in German locale', () => {
    // Non-breaking narrow space before the symbol in de-DE — normalise before
    // asserting, or this passes locally and fails on another ICU build.
    expect(formatMoney('1234.50').replace(/ | /g, ' ')).toBe('1.234,50 €');
  });

  it('accepts the string the API actually sends, without float drift', () => {
    // DRF serialises Decimal as a string precisely so this round-trip is exact.
    expect(formatMoney('0.10').replace(/ | /g, ' ')).toBe('0,10 €');
    expect(formatMoney('19.99').replace(/ | /g, ' ')).toBe('19,99 €');
  });

  it('always shows two decimals', () => {
    expect(formatMoney('100').replace(/ | /g, ' ')).toBe('100,00 €');
  });

  it('renders an em dash for null/undefined/empty rather than 0,00 €', () => {
    // "Unknown" and "zero" are different facts on a finance screen.
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney(undefined)).toBe('—');
    expect(formatMoney('')).toBe('—');
  });

  it('renders an em dash for unparseable input instead of NaN €', () => {
    expect(formatMoney('not-a-number')).toBe('—');
  });

  it('honours a different currency', () => {
    expect(formatMoney('50.00', 'USD')).toContain('50,00');
  });
});

describe('formatHours', () => {
  it('formats hours with a unit', () => {
    expect(formatHours('7.5')).toBe('7,50 h');
    expect(formatHours(0.25)).toBe('0,25 h');
  });

  it('renders an em dash for missing values', () => {
    expect(formatHours(null)).toBe('—');
  });
});

describe('formatDuration', () => {
  it('formats seconds as h:mm:ss', () => {
    expect(formatDuration(0)).toBe('0:00:00');
    expect(formatDuration(59)).toBe('0:00:59');
    expect(formatDuration(3600)).toBe('1:00:00');
    expect(formatDuration(3661)).toBe('1:01:01');
    expect(formatDuration(45296)).toBe('12:34:56');
  });

  it('omits seconds when asked', () => {
    expect(formatDuration(3661, false)).toBe('1:01');
  });

  it('clamps negatives to zero rather than rendering "-1:-1"', () => {
    // Clock skew between client and server can produce a negative elapsed time.
    expect(formatDuration(-5)).toBe('0:00:00');
  });

  it('does not roll over past 24h', () => {
    // A timer left running overnight must read 25:00:00, not 1:00:00.
    expect(formatDuration(90000)).toBe('25:00:00');
  });
});

describe('initialsOf', () => {
  it('takes first and last initials', () => {
    expect(initialsOf('Max Mustermann')).toBe('MM');
    expect(initialsOf('Anna Lena Schmidt')).toBe('AS');
  });

  it('takes two letters from a single name', () => {
    expect(initialsOf('Cher')).toBe('CH');
  });

  it('falls back for empty input', () => {
    expect(initialsOf('')).toBe('??');
    expect(initialsOf(null)).toBe('??');
    expect(initialsOf('   ')).toBe('??');
  });
});

describe('colorFromId', () => {
  const palette = ['#a', '#b', '#c'] as const;

  it('is deterministic — the same id always gets the same colour', () => {
    const id = '3f2a1b9c-0000-4000-8000-000000000000';
    expect(colorFromId(id, palette)).toBe(colorFromId(id, palette));
  });

  it('always returns a colour from the palette', () => {
    for (const id of ['a', 'bb', 'ccc', 'a-very-long-uuid-like-string']) {
      expect(palette).toContain(colorFromId(id, palette));
    }
  });

  it('handles an empty id without throwing', () => {
    expect(palette).toContain(colorFromId('', palette));
  });
});
