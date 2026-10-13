import { defineConfig, devices } from '@playwright/test'
import fs from 'node:fs'

// MEMAR e2e smoke suite. Boots the real FastAPI backend + Vite dev server and
// drives them with a real browser — this is deliberately minimal (5 scenarios),
// not a replacement for the backend's 415-test API suite in backend/tests/.

// Point Playwright at a system Chromium when one exists. Override with
// PLAYWRIGHT_CHROMIUM_EXECUTABLE if the default paths don't apply on a node.
function resolveChromiumExecutable(): string | undefined {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
  const candidates = [
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
  ]
  return candidates.find((p) => fs.existsSync(p))
}

// NOTE: 9000 is intentionally avoided — it's MEMAR's real dev/prod backend
// port (see docker-compose.yml), and this cluster often has a live instance
// bound there. Playwright's `reuseExistingServer` will silently attach to
// *any* server already answering the health-check URL, so reusing 9000 risks
// running these tests against real infrastructure instead of the ephemeral
// fixture below. Use an unrelated port for the e2e backend.
const BACKEND_PORT = 9491
const FRONTEND_PORT = 5173

// Dedicated short-TTL stack for token-expiry.spec.ts ONLY. It runs a SECOND
// backend whose access/refresh TTLs are a few seconds (via the
// MEMAR_*_TOKEN_EXPIRE_SECONDS env overrides in backend/app/auth.py) so the spec
// can drive GENUINE server-side expiry in real time. It must be isolated from
// the normal stack above: a 2s access TTL would break the 9 other tests (each
// makes several requests over several seconds). Separate ports + its own DB +
// its own Playwright project (see `projects` below) keep the blast radius zero.
// The short-TTL backend is a separate uvicorn process, so slowapi's in-process
// rate limiter gives it its OWN 10/min-per-IP bucket — the 2 logins this spec
// performs don't touch the main suite's ~9/10 budget.
const EXPIRY_BACKEND_PORT = 9492
const EXPIRY_FRONTEND_PORT = 5174
// Access expires fast; refresh outlives it by a window wide enough for the
// silent-refresh case but short enough that the full-death case can wait it out.
const EXPIRY_ACCESS_TTL_SECONDS = 2
const EXPIRY_REFRESH_TTL_SECONDS = 8

const chromiumExecutable = resolveChromiumExecutable()
const chromiumLaunch = chromiumExecutable
  ? { executablePath: chromiumExecutable, args: ['--no-sandbox'] }
  : { args: ['--no-sandbox'] }

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: 'list',
  use: {
    // "localhost" (not 127.0.0.1) so the browser's page origin matches the
    // backend's default MEMAR_CORS_ORIGINS allow-list (http://localhost:5173).
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      // Everything EXCEPT the short-TTL expiry spec runs against the normal-TTL
      // stack. Excluding it here is what keeps a 2s access TTL from ever reaching
      // the 9 other tests.
      testIgnore: /token-expiry\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: chromiumLaunch,
      },
    },
    {
      // token-expiry.spec.ts ONLY, pointed at the dedicated short-TTL frontend +
      // backend so real server-side expiry happens within the test's runtime.
      name: 'expiry',
      testMatch: /token-expiry\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: `http://localhost:${EXPIRY_FRONTEND_PORT}`,
        launchOptions: chromiumLaunch,
      },
    },
  ],
  webServer: [
    {
      // LD_LIBRARY_PATH: on NixOS the backend's venv-installed `greenlet` (a
      // manylinux wheel) can't dlopen libstdc++.so.6 out of the box — nix-ld's
      // NIX_LD_LIBRARY_PATH already has a working copy, so reuse it. Without
      // this, uvicorn's lifespan startup crashes on the first DB connection.
      // (Playwright runs `command` through a shell already, so no need to
      // wrap it in an extra `bash -c "..."` — that just doubles the quoting.)
      command: [
        'rm -f /tmp/memar-e2e.db',
        '&& mkdir -p /tmp/memar-e2e-data',
        '&& cd ../backend',
        '&& LD_LIBRARY_PATH="${NIX_LD_LIBRARY_PATH:-}:${LD_LIBRARY_PATH:-}"',
        'PYTHONPATH=.',
        'MEMAR_JWT_SECRET=e2e-test-secret-not-for-production',
        'MEMAR_ADMIN_USER=admin',
        'MEMAR_ADMIN_PASSWORD=e2e-test-pass-123',
        'MEMAR_DB_PATH=/tmp/memar-e2e.db',
        'MEMAR_DATA_DIR=/tmp/memar-e2e-data',
        'MEMAR_LICENSE_HEARTBEAT_URL=',
        `../.venv/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      ].join(' '),
      url: `http://127.0.0.1:${BACKEND_PORT}/api/healthz`,
      // Deliberately NOT reused across runs — this must always be the fresh
      // ephemeral fixture DB, never an accidental attach to a stray process.
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // VITE_API_BASE_URL bypasses vite.config.ts's hardcoded dev proxy
      // (127.0.0.1:9000, MEMAR's real dev/prod port) so the frontend talks
      // directly to the isolated e2e backend instead.
      command: `VITE_API_BASE_URL=http://localhost:${BACKEND_PORT} npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Short-TTL backend for token-expiry.spec.ts. Identical to the primary
      // backend except: its own port, its own ephemeral DB, and the
      // MEMAR_*_TOKEN_EXPIRE_SECONDS overrides that make access/refresh expire in
      // seconds. Playwright starts every entry in this array regardless of which
      // project runs, so this always boots — but only the `expiry` project's
      // frontend (below) talks to it. CORS allow-list must include :5174.
      command: [
        'rm -f /tmp/memar-e2e-expiry.db',
        '&& mkdir -p /tmp/memar-e2e-expiry-data',
        '&& cd ../backend',
        '&& LD_LIBRARY_PATH="${NIX_LD_LIBRARY_PATH:-}:${LD_LIBRARY_PATH:-}"',
        'PYTHONPATH=.',
        'MEMAR_JWT_SECRET=e2e-test-secret-not-for-production',
        'MEMAR_ADMIN_USER=admin',
        'MEMAR_ADMIN_PASSWORD=e2e-test-pass-123',
        'MEMAR_DB_PATH=/tmp/memar-e2e-expiry.db',
        'MEMAR_DATA_DIR=/tmp/memar-e2e-expiry-data',
        'MEMAR_LICENSE_HEARTBEAT_URL=',
        `MEMAR_CORS_ORIGINS=http://localhost:${EXPIRY_FRONTEND_PORT}`,
        `MEMAR_ACCESS_TOKEN_EXPIRE_SECONDS=${EXPIRY_ACCESS_TTL_SECONDS}`,
        `MEMAR_REFRESH_TOKEN_EXPIRE_SECONDS=${EXPIRY_REFRESH_TTL_SECONDS}`,
        `../.venv/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port ${EXPIRY_BACKEND_PORT}`,
      ].join(' '),
      url: `http://127.0.0.1:${EXPIRY_BACKEND_PORT}/api/healthz`,
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Short-TTL frontend: same Vite dev server, pointed at the short-TTL
      // backend. The `expiry` project's baseURL targets this port.
      command: `VITE_API_BASE_URL=http://localhost:${EXPIRY_BACKEND_PORT} npm run dev -- --port ${EXPIRY_FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${EXPIRY_FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
