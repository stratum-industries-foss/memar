import { test, expect } from '@playwright/test'
import { login } from './fixtures'

test('logout returns to the login screen', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})
