import { test, expect } from '@playwright/test'
import { login } from './fixtures'

// GENUINE server-side token expiry — the case session-lifecycle.spec.ts's
// bogus-token test can't reach. This spec runs against the dedicated short-TTL
// backend (playwright.config.ts `expiry` project + its own webServer): access
// tokens expire in ~2s and refresh tokens in ~8s of REAL time, so a valid token
// minted at login actually expires server-side while the tab is open.
//
// Key harness technique — pause the app on about:blank during the wait. Once
// logged in, the dashboard's pollers auto-refresh on every 401, which would keep
// ROTATING the refresh token (each rotation mints a fresh 8s TTL) and the session
// would never die. Parking on about:blank runs no MEMAR JS, so the tokens sit
// untouched in localStorage and expire on the real server clock. Returning to
// '/' then re-runs initializeAuth() against genuinely-expired tokens.
//
// Rate limit: this backend is a separate uvicorn process, so slowapi's
// in-process limiter gives it its own 10/min-per-IP bucket. The 2 logins here
// don't touch the main suite's ~9/10 budget.

const ACCESS_TTL_MS = 2_000
const REFRESH_TTL_MS = 8_000

test('a valid access token that expires server-side is transparently refreshed — session stays alive', async ({ page }) => {
  // Real login → real access (2s) + real refresh (8s) tokens in localStorage.
  await login(page)

  // Park the app so no poller refreshes the token behind our back, and wait past
  // the access TTL but well inside the refresh TTL.
  await page.goto('about:blank')
  await page.waitForTimeout(ACCESS_TTL_MS + 1_500) // ~3.5s: access dead, refresh alive

  // Arm the assertion BEFORE navigating: the App renders the dashboard
  // OPTIMISTICALLY from the restored (expired) token before any request fires, so
  // "dashboard visible" alone proves nothing. The load-bearing proof is that the
  // now-expired access token drives a REAL /api/auth/refresh that succeeds (200) —
  // this exercises the Tier-1 single-flight refresh under genuine server expiry.
  const refreshResponse = page.waitForResponse(
    (r) => r.url().includes('/api/auth/refresh') && r.request().method() === 'POST',
    { timeout: 10_000 },
  )

  await page.goto('/')

  expect((await refreshResponse).status()).toBe(200)
  // Transparently refreshed → still on the dashboard, never bounced to login.
  await expect(page.getByText('Universal equipment fleet monitor')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByLabel('Username', { exact: true })).toHaveCount(0)
})

test('when both tokens expire server-side, the app routes to the login screen (not a silent demo downgrade)', async ({ page }) => {
  await login(page)

  // Park the app and wait past BOTH the access and refresh TTLs so the whole
  // session is genuinely dead on the server — no rotation kept it alive.
  await page.goto('about:blank')
  await page.waitForTimeout(REFRESH_TTL_MS + 2_000) // ~10s: access AND refresh dead

  // On return, initializeAuth() restores the (expired) tokens and optimistically
  // shows the dashboard; the first authed request 401s, the refresh attempt is
  // rejected (refresh token expired server-side), 'memar:unauthorized' fires, and
  // because a real session had been restored (hadRealSession) the app routes to
  // the real login screen rather than downgrading into demo. getByLabel auto-waits
  // through the brief optimistic-dashboard phase to the eventual bounce.
  await page.goto('/')

  await expect(page.getByLabel('Username', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})
