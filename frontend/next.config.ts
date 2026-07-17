import type { NextConfig } from 'next';

/**
 * Security headers.
 *
 * The API sets its own CSP for its responses; this covers the Next.js origin.
 * `unsafe-inline`/`unsafe-eval` in dev are required by the React refresh runtime
 * and are dropped in production builds.
 */
const isDev = process.env.NODE_ENV === 'development';

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const csp = [
  `default-src 'self'`,
  `script-src 'self'${isDev ? " 'unsafe-eval' 'unsafe-inline'" : ""}`,
  // Tailwind injects styles at runtime; a nonce-based policy would need a custom
  // document and buys little here since we render no untrusted HTML.
  `style-src 'self' 'unsafe-inline'`,
  `img-src 'self' data: blob:`,
  `font-src 'self' data:`,
  `connect-src 'self' ${apiUrl}${isDev ? ' ws: wss:' : ''}`,
  `frame-ancestors 'none'`,
  `base-uri 'self'`,
  `form-action 'self'`,
  `object-src 'none'`,
].join('; ');

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Fail the production build on type errors rather than shipping them.
  // (Next 16 removed the `eslint` build option along with `next lint`; linting
  // is a separate CI step — see `make lint-frontend`.)
  typescript: { ignoreBuildErrors: false },

  // Standalone output keeps the production image small (no node_modules copy).
  output: 'standalone',

  poweredByHeader: false,

  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Content-Security-Policy', value: csp },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'same-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ];
  },
};

export default nextConfig;
