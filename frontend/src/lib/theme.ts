'use client';

import * as React from 'react';

import { usePersistedBoolean } from '@/lib/persisted-state';

/**
 * Theme preference. Light is the product default; dark is an opt-in that
 * survives reloads and syncs across tabs via the persisted-state store.
 *
 * The same key is read by the inline no-flash script in the root layout, so
 * the attribute is correct before first paint — keep the two in sync.
 */
export const THEME_STORAGE_KEY = 'coreflow.theme.dark';

export function useDarkTheme(): [boolean, (dark: boolean) => void] {
  return usePersistedBoolean(THEME_STORAGE_KEY, false);
}

/** Mounted once in Providers: mirrors the preference onto <html data-theme>. */
export function ThemeSync() {
  const [dark] = useDarkTheme();

  React.useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }, [dark]);

  return null;
}
