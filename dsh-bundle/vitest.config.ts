import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const stub = () => fileURLToPath(new URL(`./tests/fixtures/stubs/dsh-stubs.ts`, import.meta.url));

export default defineConfig({
  resolve: {
    alias: [
      { find: "@deepseek-ai/dsh-tools", replacement: stub() },
      { find: "@deepseek-ai/dsh-app-boot", replacement: stub() },
    ],
  },
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
