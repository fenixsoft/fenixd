/**
 * dsh-peers.d.ts — 官方 peer 包的最小编译期面。
 *
 * 构建期（pnpm build）peer 不参与运行，只需让 tsc 完成 @deepseek-ai/* 的
 * 模块解析即可；API 形状与 tests/fixtures/stubs/dsh-stubs.ts（vitest 桩）及
 * dsh 0.2.0-rc.2 真实导出保持一致。运行期类型解析走真实安装的 peer 包。
 */

declare module "@deepseek-ai/dsh-app-boot" {
  /** 当前 dsh 运行时版本（版本钉扎校验用）。 */
  export function getDshRuntimeVersion(): string;

  /** 测试内切换桩版本（仅 stub 实现提供；真实包无此导出也不影响编译）。 */
  export function setMockDshRuntimeVersion(version: string): void;
}

declare module "@deepseek-ai/dsh-tools" {
  /**
   * dsh 工具定义编译入口：真实 dsh 里做 schema 编译与包装（非恒等）；
   * 编译期按恒等签名建模，运行期行为以真实包为准。
   */
  export function defineTool<T>(options: T): T;
}
