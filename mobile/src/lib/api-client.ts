import { supabase } from './supabase';
import { API_BASE_URL } from './constants';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const REQUEST_TIMEOUT_MS = 15_000;

// Long timeout for endpoints that block on AI calls (receipt parse +
// categorize). Real-world Claude vision parse latency is routinely
// 15-45s with tail cases up to ~60s; 90s gives a ~50% safety margin
// without letting a truly hung request hang the UI indefinitely.
export const LONG_REQUEST_TIMEOUT_MS = 90_000;

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') {
      throw new ApiError(0, 'Network timeout');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError(401, 'Not authenticated');
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
}

function buildUrl(path: string, params?: Record<string, string>): string {
  const url = `${API_BASE_URL}/api/v1${path}`;
  if (!params) return url;
  const qs = new URLSearchParams(params).toString();
  return qs ? `${url}?${qs}` : url;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    let detail: string | undefined;
    try {
      const body = await response.json();
      message = body.detail ?? body.message ?? message;
      detail = typeof body.detail === 'string' ? body.detail : undefined;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(response.status, message, detail);
  }
  if (response.status === 204) return undefined as T;
  if (response.headers.get('content-length') === '0') return undefined as T;
  return response.json() as Promise<T>;
}

export const apiClient = {
  async get<T>(path: string, params?: Record<string, string>): Promise<T> {
    const headers = await getAuthHeaders();
    const response = await fetchWithTimeout(buildUrl(path, params), { headers });
    return handleResponse<T>(response);
  },

  async post<T>(
    path: string,
    body?: unknown,
    opts?: { timeoutMs?: number },
  ): Promise<T> {
    const headers = await getAuthHeaders();
    const response = await fetchWithTimeout(
      buildUrl(path),
      {
        method: 'POST',
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      },
      opts?.timeoutMs,
    );
    return handleResponse<T>(response);
  },

  async put<T>(path: string, body?: unknown): Promise<T> {
    const headers = await getAuthHeaders();
    const response = await fetchWithTimeout(buildUrl(path), {
      method: 'PUT',
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return handleResponse<T>(response);
  },

  async upload<T>(path: string, formData: FormData): Promise<T> {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) throw new ApiError(401, 'Not authenticated');
    const response = await fetchWithTimeout(buildUrl(path), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    });
    return handleResponse<T>(response);
  },

  async del(path: string): Promise<void> {
    const headers = await getAuthHeaders();
    const response = await fetchWithTimeout(buildUrl(path), {
      method: 'DELETE',
      headers,
    });
    await handleResponse<void>(response);
  },
};
