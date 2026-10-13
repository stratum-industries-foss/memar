import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Separate from vite.config.ts on purpose: the app build config pulls in
// vite-plugin-pwa (workbox precache manifest generation), which has no
// business running under a unit-test environment. Test-only settings live
// here; if a future need arises to share app aliases/resolve config between
// the two, merge via a shared base config rather than duplicating by hand.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
    // Zero test files today is expected (this is fresh tooling, not a
    // regression) — don't fail CI/local runs until real specs land.
    passWithNoTests: true,
    // e2e/ holds Playwright specs (run via `npm run e2e`, own config +
    // runner) — exclude them here or vitest's default *.spec.ts glob picks
    // them up and chokes on `test()` from @playwright/test.
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
  },
})
