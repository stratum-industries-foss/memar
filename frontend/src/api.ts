/**
 * MEMAR API Client - Centralized fetch wrapper with auth management
 *
 * This module provides:
 * - Module-level auth state (survives React renders)
 * - Token persistence (refresh token → localStorage)
 * - Auto-refresh on 401 responses
 * - Unified Authorization header injection
 *
 * No React dependencies. Pure TypeScript/JS module.
 */

export interface AuthState {
  accessToken: string | null
  refreshToken: string | null
}

// Module-level auth state — single source of truth across React renders
export const authState: AuthState = {
  accessToken: null,
  refreshToken: null,
}

// API base URL from Vite env or empty string (dev proxy at /api)
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

// localStorage keys (use dashes for consistency with App.tsx)
const ACCESS_TOKEN_KEY = 'memar-access-token'
const REFRESH_TOKEN_KEY = 'memar-refresh-token'

/**
 * Update access & refresh tokens in authState and persist to localStorage
 *
 * @param access - New access token (ephemeral, 15min typical)
 * @param refresh - New refresh token (persisted to localStorage)
 */
export function setTokens(access: string, refresh: string): void {
  authState.accessToken = access
  authState.refreshToken = refresh
  // ACCEPTED RISK (pre-launch): JWTs in localStorage. Post-launch migration to httpOnly cookies tracked separately — no XSS sink today.
  localStorage.setItem(ACCESS_TOKEN_KEY, access)
  localStorage.setItem(REFRESH_TOKEN_KEY, refresh)
}

/**
 * Clear both tokens from authState and localStorage
 * Called on logout or when refresh fails
 */
export function clearTokens(): void {
  authState.accessToken = null
  authState.refreshToken = null
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

/**
 * Retrieve refresh token from localStorage
 * Used on page load to restore session or when authState.refreshToken is cleared
 *
 * @returns Refresh token string or null if not found
 */
export function loadStoredRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

/**
 * Result of a refresh attempt.
 *
 * - 'refreshed'   — new token pair obtained; retry the original request.
 * - 'auth_failed' — the refresh token was definitively rejected (401/403 or
 *                   missing). Clear session and log out for real.
 * - 'transient'   — network error / fetch threw / non-auth 5xx. Tokens are
 *                   left intact so the caller can propagate the original 401
 *                   and retry later without destroying the session.
 */
export type RefreshResult = 'refreshed' | 'auth_failed' | 'transient'

// Single-flight guard: concurrent 401s share ONE refresh attempt so the
// single-use refresh token is only spent once. Without this, ~6 concurrent
// pollers each spend the same token; the first wins and invalidates it, the
// rest get 401 and log the user out.
let refreshInFlight: Promise<RefreshResult> | null = null

/**
 * Attempt to refresh the access token using the refresh token.
 *
 * Single-flight: if a refresh is already in progress, callers await the same
 * promise instead of starting a second one.
 *
 * Failure is discriminated:
 * - Definitive auth failure (401/403 or no refresh token) → clear tokens,
 *   return 'auth_failed'.
 * - Transient failure (network error, thrown fetch, non-auth 5xx) → keep
 *   tokens, return 'transient'.
 *
 * @returns RefreshResult
 */
export async function refreshAccessToken(): Promise<RefreshResult> {
  // If a refresh is already in flight, share it — don't spend the token twice.
  if (refreshInFlight) {
    return refreshInFlight
  }

  refreshInFlight = (async (): Promise<RefreshResult> => {
    // Get refresh token from authState or localStorage
    const refreshToken = authState.refreshToken || loadStoredRefreshToken()
    if (!refreshToken) {
      // Nothing to refresh with — definitive auth failure.
      return 'auth_failed'
    }

    try {
      const response = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })

      if (!response.ok) {
        // Only 401/403 mean the refresh token itself is invalid → real logout.
        // Any other non-ok status (5xx, gateway errors) is transient: keep the
        // session and let the poller retry.
        if (response.status === 401 || response.status === 403) {
          clearTokens()
          return 'auth_failed'
        }
        return 'transient'
      }

      const data = (await response.json()) as {
        access_token: string
        refresh_token: string
      }
      setTokens(data.access_token, data.refresh_token)
      return 'refreshed'
    } catch {
      // Network error or parse failure — do NOT clear tokens. A blip must not
      // destroy the session; propagate the original 401 and retry later.
      return 'transient'
    }
  })()

  try {
    return await refreshInFlight
  } finally {
    // Clear the guard once the shared attempt settles so the next real 401
    // (after this token is genuinely stale) can start a fresh refresh.
    refreshInFlight = null
  }
}

/**
 * Main API fetch wrapper with auth injection and auto-refresh
 *
 * Flow:
 * 1. Inject Authorization header if accessToken exists
 * 2. Perform fetch
 * 3. If 401 AND refreshToken exists: attempt refresh + retry
 * 4. If refresh fails: fire 'memar:unauthorized' event and return 401 response
 * 5. Otherwise: return response as-is
 *
 * @param input - URL path (e.g. '/api/printers')
 * @param init - Optional RequestInit (method, body, headers, etc.)
 * @returns Response object (caller responsible for .json(), .text(), etc.)
 *
 * @example
 * const res = await apiFetch('/api/printers')
 * const data = await res.json()
 *
 * @example
 * const res = await apiFetch('/api/printers/1/temperature', {
 *   method: 'POST',
 *   headers: { 'Content-Type': 'application/json' },
 *   body: JSON.stringify({ target: 200 })
 * })
 */
export async function apiFetch(
  input: string,
  init?: RequestInit
): Promise<Response> {
  // Build headers from init or create new Headers
  const headers = new Headers(init?.headers)

  // Inject Authorization header if we have an access token
  if (authState.accessToken) {
    headers.set('Authorization', `Bearer ${authState.accessToken}`)
  }

  // Perform initial fetch
  let res = await fetch(`${API_BASE}${input}`, { ...init, headers })

  // T74: Handle 403 with password_change_required flag — redirect to forced change UI
  if (res.status === 403) {
    const cloned = res.clone()
    try {
      const body = await cloned.json() as { password_change_required?: boolean }
      if (body.password_change_required) {
        window.dispatchEvent(new CustomEvent('memar:password_change_required'))
      }
    } catch {
      // Body not JSON or parse error — ignore and return original response
    }
  }

  // T77: Handle 402 — extract detail and fire event for UI to show
  if (res.status === 402) {
    const cloned = res.clone()
    try {
      const body = await cloned.json() as { detail?: string }
      const detail = body.detail || 'Payment required'
      window.dispatchEvent(new CustomEvent('memar:payment_required', { detail }))
    } catch {
      window.dispatchEvent(new CustomEvent('memar:payment_required', { detail: 'Payment required' }))
    }
  }

  // Handle 401: attempt refresh if we have a refresh token
  if (res.status === 401 && authState.refreshToken) {
    const result = await refreshAccessToken()

    if (result === 'refreshed') {
      // Retry the original request with the new token.
      headers.set('Authorization', `Bearer ${authState.accessToken!}`)
      res = await fetch(`${API_BASE}${input}`, { ...init, headers })
    } else if (result === 'auth_failed') {
      // Definitive auth failure: the refresh token was rejected → real logout.
      clearTokens()
      window.dispatchEvent(new CustomEvent('memar:unauthorized'))
    }
    // result === 'transient': network blip / non-auth error. Leave tokens
    // intact and return the original 401 so the poller simply retries later —
    // the session survives the blip.
  }

  return res
}

/**
 * Initialize auth state from localStorage on app start
 * Called once on page load to restore session from persisted tokens
 */
export function initializeAuth(): void {
  const storedAccessToken = localStorage.getItem(ACCESS_TOKEN_KEY)
  const storedRefreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
  if (storedAccessToken) {
    authState.accessToken = storedAccessToken
  }
  if (storedRefreshToken) {
    authState.refreshToken = storedRefreshToken
  }
}

/**
 * Throw if the response is not ok, extracting detail from JSON body if available
 *
 * @param res - Response to check
 * @returns The same response if ok
 * @throws Error with detail message or HTTP status
 */
export async function requireOk(res: Response): Promise<Response> {
  if (res.ok) return res
  const body = await res.json().catch(() => ({} as { detail?: string }))
  const detail = typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`
  throw new Error(detail)
}
