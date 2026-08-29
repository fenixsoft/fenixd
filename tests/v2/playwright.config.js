import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '.',
  timeout: 30000,
  use: { baseURL: process.env.PLAYWRIGHT_TEST_BASE_URL || 'http://127.0.0.1:8787' },
});
