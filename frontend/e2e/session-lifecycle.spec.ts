import { test, expect } from '@playwright/test'
import { login } from './fixtures'

// Session persistence + de-auth routing. Tokens live in localStorage under
// 'memar-access-token' / 'memar-refresh-token' (src/api.ts). On load,
// initializeAuth() restores them; a restored token skips the demo auto-login.
//
// NOTE: these tests keep login count low on purpose — /api/auth/login is rate
// limited to 10/minute per IP and the e2e DB is NOT reset between tests, so all
// logins in a run share one bucket. (See the report's rate-limit note.)

const ACCESS_TOKEN_KEY = 'memar-access-token'
const REFRESH_TOKEN_KEY = 'memar-refresh-token'

test('a logged-in session survives a full page reload', async ({ page }) => {
  await login(page)
  await page.reload()
  // Restored token → still on the dashboard, no re-login required.
  await expect(page.getByText('Universal equipment fleet monitor')).toBeVisible({ timeout: 10_000 })
})

test('clearing the stored tokens routes back to login, not a silent demo session', async ({ page }) => {
  await login(page)

  // Simulate the session's tokens disappearing (logout in another tab / cleared
  // storage), then reload. With no token to restore, App probes /api/auth/demo,
  // which 404s in this harness — so it must land on the real login screen rather
  // than silently downgrading into a read-only demo/viewer session.
  await page.evaluate(({ a, r }) => {
    localStorage.removeItem(a)
    localStorage.removeItem(r)
  }, { a: ACCESS_TOKEN_KEY, r: REFRESH_TOKEN_KEY })
  await page.reload()

  await expect(page.getByLabel('Username', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})

test('an invalid/expired stored token routes to login instead of a silent demo downgrade', async ({ page }) => {
  // No UI login here (0 logins against the rate limit): seed a bogus token pair
  // directly. On reload, initializeAuth() restores it and App optimistically
  // shows the dashboard, but the first authenticated request 401s; the refresh
  // attempt with the bogus refresh token is rejected (backend returns 401 for an
  // unknown refresh token), which fires 'memar:unauthorized'. Because a token
  // was restored (hadRealSession), App routes to the login screen — it must NOT
  // fall back to demo. This simulates client-side handling of an expired session
  // without needing backend token-TTL control.
  await page.goto('/')
  await page.evaluate(({ a, r }) => {
    localStorage.setItem(a, 'bogus.invalid.token')
    localStorage.setItem(r, 'bogus-refresh-token')
  }, { a: ACCESS_TOKEN_KEY, r: REFRESH_TOKEN_KEY })
  await page.reload()

  await expect(page.getByLabel('Username', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})
