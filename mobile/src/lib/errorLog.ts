import { ApiError } from './api-client';

export type LogEntry = {
  ts: number;
  scope: string;
  message: string;
  status?: number;
  detail?: string;
  context?: Record<string, unknown>;
};

const RING_SIZE = 50;
const ring: LogEntry[] = [];

export function logError(
  scope: string,
  error: unknown,
  context?: Record<string, unknown>,
): void {
  const entry: LogEntry = {
    ts: Date.now(),
    scope,
    message: error instanceof Error ? error.message : String(error),
    status: error instanceof ApiError ? error.status : undefined,
    detail: error instanceof ApiError ? error.detail : undefined,
    context,
  };
  ring.push(entry);
  if (ring.length > RING_SIZE) ring.shift();
  if (__DEV__) {
    // eslint-disable-next-line no-console
    console.error(`[${scope}]`, entry.message, entry.status ?? '', context ?? '');
  }
  // TODO(observability): wire to Sentry/PostHog here when a provider is chosen.
  // Keep this module as the single chokepoint so the swap is one diff.
}

export function getRecentErrors(): readonly LogEntry[] {
  return ring;
}
