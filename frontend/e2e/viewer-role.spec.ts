import { test, expect } from '@playwright/test'
import { ADMIN_USER, ADMIN_PASSWORD, login } from './fixtures'

// A "viewer" is a read-only role: it must reach the dashboard but see none of
// the write/control affordances (Admin panel, +Add device, floor-plan Edit).
//
// This e2e backend does NOT run with MEMAR_DEMO_MODE, so /api/auth/demo 404s
// (see dashboard-console-errors.spec.ts) and there is no built-in viewer login.
// Instead we mint a viewer through the real admin API — the default "free" tier
// is active with the full feature set (incl. multi_user), so POST
// /api/admin/users is allowed — then log in as that viewer through the UI.

// Backend origin — matches BACKEND_PORT in playwright.config.ts. The frontend
// talks to this same origin via VITE_API_BASE_URL; from Node there is no CORS.
const BACKEND = 'http://localhost:9491'
const VIEWER_USER = 'viewer_e2e'
const VIEWER_PASSWORD = 'viewer-e2e-pass-123' // >= 8 chars (CreateUserRequest min)

test('a viewer reaches the dashboard but sees no write/control affordances', async ({ page, request }) => {
  // ── provision a viewer via the admin API ──────────────────────────────────
  const adminLogin = await request.post(`${BACKEND}/api/auth/login`, {
    data: { username: ADMIN_USER, password: ADMIN_PASSWORD },
  })
  expect(adminLogin.ok(), `admin login failed: ${adminLogin.status()}`).toBeTruthy()
  const { access_token: adminToken } = (await adminLogin.json()) as { access_token: string }

  const createViewer = await request.post(`${BACKEND}/api/admin/users`, {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { username: VIEWER_USER, password: VIEWER_PASSWORD, role: 'viewer' },
  })
  // 201 on first run, 409 if a prior run already created it (DB persists for the
  // life of the webServer). Either is fine for logging in below.
  expect([201, 409], `create viewer failed: ${createViewer.status()}`).toContain(createViewer.status())

  // ── log in through the UI as that viewer ──────────────────────────────────
  await login(page, VIEWER_USER, VIEWER_PASSWORD)

  // Positive control: an unguarded toolbar button proves the dashboard toolbar
  // fully rendered, so the absence assertions below are meaningful (not just a
  // not-yet-rendered race).
  await expect(page.getByRole('button', { name: 'Fleet settings' })).toBeVisible()

  // Admin panel is admin-only (userRole === 'admin').
  await expect(page.getByRole('button', { name: 'Admin', exact: true })).toHaveCount(0)
  // "+ Add device" is write-gated (canWrite = admin || operator).
  await expect(page.getByRole('button', { name: '+ Add device' })).toHaveCount(0)
  // Floor-plan "Edit Layout" is gated by canEdit=canWrite.
  await expect(page.getByRole('button', { name: /Edit Layout/ })).toHaveCount(0)
})
