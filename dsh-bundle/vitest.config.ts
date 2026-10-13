import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const stub = (name: string) => fileURLToPath(new URL(`./tests/fixtures/stubs/dsh-stubs.ts`, import.meta.url));

export default defineConfig({
  resolve: {
    alias: [
      { find: "@deepseek-ai/dsh-tools", replacement: stub("dsh-tools") },
      { find: "@deepseek-ai/dsh-app-boot", replacement: stub("dsh-app-boot") },
    ],
  },
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
