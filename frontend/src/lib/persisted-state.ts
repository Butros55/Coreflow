'use client';

import * as React from 'react';

/**
 * Read/write a localStorage value as a React external store.
 *
 * Why not `useState` + `useEffect`: localStorage is external state, and reading
 * it during render would mismatch the server-rendered HTML. The usual fix
 * (setState inside an effect) causes a cascading re-render on every mount and is
 * what `react-hooks/set-state-in-effect` warns about. `useSyncExternalStore` is
 * the built-in answer — and it gives cross-tab sync for free, because the
 * browser fires `storage` in other tabs.
 */
interface PersistedStore<T> {
  get: () => T;
  set: (value: T) => void;
  subscribe: (listener: () => void) => () => void;
}

function createStore<T>(
  key: string,
  defaultValue: T,
  parse: (raw: string) => T,
): PersistedStore<T> {
  const listeners = new Set<() => void>();
  // Cached so getSnapshot returns a referentially stable value; returning a
  // fresh object each call would loop useSyncExternalStore forever.
  let cache: T | undefined;
  let cachedRaw: string | null | undefined;

  const emit = () => listeners.forEach((listener) => listener());

  return {
    get: () => {
      if (typeof window === 'undefined') return defaultValue;
      const raw = window.localStorage.getItem(key);
      if (raw !== cachedRaw) {
        cachedRaw = raw;
        cache = raw === null ? defaultValue : parse(raw);
      }
      return cache as T;
    },
    set: (value: T) => {
      if (typeof window === 'undefined') return;
      window.localStorage.setItem(key, String(value));
      cachedRaw = undefined; // Invalidate; next get() re-reads.
      emit();
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      // `storage` only fires in *other* tabs, hence the local listener set too.
      const onStorage = (event: StorageEvent) => {
        if (event.key === key) {
          cachedRaw = undefined;
          listener();
        }
      };
      window.addEventListener('storage', onStorage);
      return () => {
        listeners.delete(listener);
        window.removeEventListener('storage', onStorage);
      };
    },
  };
}

const booleanStores = new Map<string, PersistedStore<boolean>>();

export function usePersistedBoolean(
  key: string,
  defaultValue = false,
): [boolean, (value: boolean) => void] {
  let store = booleanStores.get(key);
  if (!store) {
    store = createStore(key, defaultValue, (raw) => raw === 'true');
    booleanStores.set(key, store);
  }
  const activeStore = store;

  const value = React.useSyncExternalStore(
    activeStore.subscribe,
    activeStore.get,
    // Server snapshot: the default, so SSR output is deterministic.
    () => defaultValue,
  );

  const setValue = React.useCallback((next: boolean) => activeStore.set(next), [activeStore]);

  return [value, setValue];
}
