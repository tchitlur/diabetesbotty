import { defineConfig, devices } from '@playwright/test'

// The v6 UI proof: desktop at 1440 px, then three phones (two real device descriptors and a bare 375x667).
export default defineConfig({
  testDir: '.',
  testMatch: /audit_v6\.spec\.ts/,
  timeout: 900_000,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:5173', headless: true, actionTimeout: 30_000 },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'iphone13', use: { ...devices['iPhone 13'] } },
    { name: 'pixel5', use: { ...devices['Pixel 5'] } },
    { name: 'bare375', use: { viewport: { width: 375, height: 667 }, isMobile: true, hasTouch: true } },
  ],
})
