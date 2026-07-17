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
  themeColor: '#070b18',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" data-theme="dark" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
