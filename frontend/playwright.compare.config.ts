import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: /audit_compare\.spec\.ts/,
  timeout: 600_000,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: { headless: true, actionTimeout: 30_000 },
})
