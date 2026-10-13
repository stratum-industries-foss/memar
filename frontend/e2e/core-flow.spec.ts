import { test, expect } from '@playwright/test'
import { login } from './fixtures'

// Smoke coverage for the main dashboard surface: if a broad regression broke the
// fleet view, its printer rows, the workspace drawer, or the add-device modal,
// this fails CI. The e2e backend boots with a populated fleet (seeded devices),
// so real printer rows render and a workspace drawer can be opened.

test('the fleet dashboard renders printers and opens a printer workspace + add-device dialog', async ({ page }) => {
  await login(page)

  // Main fleet surface + at least one real printer row.
  await expect(page.getByRole('heading', { name: 'Fleet Matrix' })).toBeVisible({ timeout: 10_000 })
  // Exclude the column-header row (shares the .fleet-matrix-row class) to target
  // a real, clickable printer row.
  const rows = page.locator('.fleet-matrix-row:not(.fleet-matrix-header-row)')
  await expect(rows.first()).toBeVisible()

  // Opening a printer row raises the workspace drawer; its "Close" button
  // dismisses it (must close before touching the topbar, which the drawer
  // overlay covers).
  await rows.first().click()
  const workspace = page.getByRole('dialog', { name: 'Printer workspace' })
  await expect(workspace).toBeVisible()
  await workspace.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(workspace).toHaveCount(0)

  // Primary write surface: the Add-device modal opens and closes.
  await page.getByRole('button', { name: '+ Add device' }).click()
  const addDialog = page.getByRole('dialog', { name: 'Add device' })
  await expect(addDialog).toBeVisible()
  await page.getByRole('button', { name: 'Close add device' }).click()
  await expect(addDialog).toHaveCount(0)
})
