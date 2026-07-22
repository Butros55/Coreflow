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

// Docker dev: bind mounts on Windows/macOS hosts don't forward file-change
// events into the container, so docker-compose.yml sets WATCH_POLL_INTERVAL_MS
// and the dev server polls instead. Webpack honors it via watchOptions.poll;
// Turbopack accepts the option too but its poll watcher detects nothing on
// these mounts as of Next 16.2 (vercel/next.js#68255) — hence the container
// runs `dev:docker` (--webpack). Unset — e.g. `npm run dev` directly on the
// host — keeps the cheaper event-based watching.
const watchPollMs = Number(process.env.WATCH_POLL_INTERVAL_MS);

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

  ...(watchPollMs > 0 ? { watchOptions: { pollIntervalMs: watchPollMs } } : {}),

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
