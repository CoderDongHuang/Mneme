import { defineConfig } from '@playwright/test'
import process from 'node:process'
const externalBaseUrl = process.env.MNEME_E2E_BASE_URL
export default defineConfig({
  testDir: './e2e', timeout: 30000, retries: 1,
  use: { baseURL: externalBaseUrl || 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  webServer: externalBaseUrl ? undefined : { command: 'npm run preview -- --port 4173', port: 4173, reuseExistingServer: true },
  projects: [
    { name: '桌面端', use: { viewport: { width: 1440, height: 900 } } },
    { name: '移动端', use: { viewport: { width: 390, height: 844 } } },
  ],
})
