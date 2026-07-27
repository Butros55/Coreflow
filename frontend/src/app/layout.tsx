import type { Metadata, Viewport } from 'next';

import { Providers } from '@/app/providers';

import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'Coreflow',
    template: '%s · Coreflow',
  },
  description:
    'Zentrale Arbeitsoberfläche für Kunden, Projekte, Zeiterfassung, Rechnungen und Finanzen.',
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: '#f3f4fb',
  width: 'device-width',
  initialScale: 1,
};

/**
 * Applies the persisted theme before first paint so a dark-mode user never
 * sees a light flash. Must read the same key as `lib/theme.ts`.
 */
const THEME_INIT_SCRIPT = `(function(){try{var dark=localStorage.getItem('coreflow.theme.dark')==='true';document.documentElement.dataset.theme=dark?'dark':'light';}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" data-theme="light" suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
