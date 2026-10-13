import { test, expect } from '@playwright/test'

test('app loads and shows the login screen when unauthenticated', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Password', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})
