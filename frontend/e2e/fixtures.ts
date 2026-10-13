import type { Page } from '@playwright/test'
import { expect } from '@playwright/test'

// Must match playwright.config.ts's webServer env for the backend process.
export const ADMIN_USER = 'admin'
export const ADMIN_PASSWORD = 'e2e-test-pass-123'

/** Fill the login form and submit, waiting for the dashboard to render. */
export async function login(page: Page, username = ADMIN_USER, password = ADMIN_PASSWORD) {
  await page.goto('/')
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  // Dashboard topbar renders "Universal equipment fleet monitor" once logged in.
  await expect(page.getByText('Universal equipment fleet monitor')).toBeVisible({ timeout: 10_000 })
}
