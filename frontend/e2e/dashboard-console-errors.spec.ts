import { test, expect } from '@playwright/test'
import { ADMIN_USER, ADMIN_PASSWORD } from './fixtures'

// Chrome logs any non-2xx network response as a console "error" entry
// ("Failed to load resource: the server responded with a status of 404")
// regardless of whether app code called console.error(). That text alone
// doesn't include the URL, so we correlate against the actual failed
// responses instead of pattern-matching console text.
//
// Two failed requests are expected here and are not app bugs:
//   - GET /api/auth/demo -> 404: App.tsx always probes this on mount to
//     auto-login as "demo" when MEMAR_DEMO_MODE is set; it's disabled in this
//     e2e fixture on purpose (scenario 1 needs the real login screen), so the
//     probe 404s by design.
//   - GET /api/settings/fleet -> 401: fetched by an effect that fires before
//     the access token is set on first mount.
// Both fire twice because src/main.tsx wraps <App> in React.StrictMode,
// which double-invokes effects in dev builds only.
const ALLOWED_FAILED_REQUESTS = [
  { urlSuffix: '/api/auth/demo', status: 404 },
  { urlSuffix: '/api/settings/fleet', status: 401 },
]

function isAllowedFailure(url: string, status: number): boolean {
  return ALLOWED_FAILED_REQUESTS.some((a) => url.endsWith(a.urlSuffix) && status === a.status)
}

test('fleet dashboard renders without a JS console error', async ({ page }) => {
  const consoleErrors: string[] = []
  const unexpectedFailedRequests: string[] = []

  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    // Network-load failures are asserted separately (with URL context) below.
    if (/^Failed to load resource:/.test(msg.text())) return
    consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`))
  page.on('response', (resp) => {
    if (resp.status() >= 400 && !isAllowedFailure(resp.url(), resp.status())) {
      unexpectedFailedRequests.push(`${resp.status()} ${resp.url()}`)
    }
  })

  await page.goto('/')
  await page.getByLabel('Username', { exact: true }).fill(ADMIN_USER)
  await page.getByLabel('Password', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Universal equipment fleet monitor')).toBeVisible({ timeout: 10_000 })

  // Let the WebSocket connect + first fleet payload land.
  await page.waitForTimeout(1000)

  expect(consoleErrors, `unexpected console.error / pageerror during login+dashboard load:\n${consoleErrors.join('\n')}`).toEqual([])
  expect(unexpectedFailedRequests, `unexpected failed network requests during login+dashboard load:\n${unexpectedFailedRequests.join('\n')}`).toEqual([])
})
