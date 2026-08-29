import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '.',
  timeout: 30000,
  use: { baseURL: process.env.V2_BASE_URL || 'http://127.0.0.1:8787' },
});
