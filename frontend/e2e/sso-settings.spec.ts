import { test, expect } from '@playwright/test'
import { login } from './fixtures'

test('SSO settings tab in the admin panel renders the form', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: 'Admin', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Admin' })).toBeVisible()

  await page.getByRole('button', { name: 'SSO', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: 'Admin' })
  await expect(dialog.getByText('OIDC', { exact: true })).toBeVisible()
  await expect(dialog.getByPlaceholder('https://idp.example.com')).toBeVisible()
})
