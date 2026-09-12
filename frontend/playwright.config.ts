import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: /audit\.spec\.ts/,
  timeout: 600_000,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
    headless: true,
    actionTimeout: 30_000,
  },
})
