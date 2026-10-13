import { test, expect } from '@playwright/test'
import { login } from './fixtures'

test('login with admin credentials succeeds and reaches the dashboard', async ({ page }) => {
  await login(page)
  // Admin-only control that only renders once the /api/auth/me role comes back "admin".
  await expect(page.getByRole('button', { name: 'Admin', exact: true })).toBeVisible()
})
