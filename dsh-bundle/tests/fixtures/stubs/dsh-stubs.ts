/**
 * dsh-stubs.ts — vitest 装载桩：Bundle 单测不依赖真实 dsh 安装。
 * vitest.config.ts 把 @deepseek-ai/dsh-tools / @deepseek-ai/dsh-app-boot
 * 别名到本文件；只暴露被测代码实际消费的 API 面。
 */

// ── @deepseek-ai/dsh-tools 桩 ──────────────────────────────────────────────
// defineTool 在真实 dsh 里做 schema 编译与包装；桩按恒等返回，让测试直接
// 断言传入的工具定义对象（name/parameters/execute/output）。
export function defineTool<T>(options: T): T {
  return options;
}

// ── @deepseek-ai/dsh-app-boot 桩 ───────────────────────────────────────────
let mockRuntimeVersion = "0.2.0-rc.2";

/** 测试内切换桩版本（版本钉扎 fail-fast 用例）。 */
export function setMockDshRuntimeVersion(version: string): void {
  mockRuntimeVersion = version;
}

export function getDshRuntimeVersion(): string {
  return mockRuntimeVersion;
}
