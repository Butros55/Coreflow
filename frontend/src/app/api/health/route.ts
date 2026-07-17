import { NextResponse } from 'next/server';

/**
 * Frontend liveness probe (used by the compose healthcheck).
 *
 * Checks only that the Next.js server responds. It deliberately does not probe
 * the backend: the frontend being up and the API being up are separate
 * questions, and conflating them would restart the frontend during an API blip.
 */
export const dynamic = 'force-dynamic';

export function GET() {
  return NextResponse.json({ status: 'ok', service: 'coreflow-frontend' });
}
