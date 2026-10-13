/**
 * index.ts — fenix-dsh-bundle 装配入口（Task 工具族 + 三守卫 + 审批校验）。
 *
 * Bundle 是「数据包」：package.json 的 dsh.bundle.patch 指向 cordis.patch.yml，
 * patch 行引用本模块（fenix-dsh-bundle）与 ./modelConfig（fenix-model-config）。
 * 版本钉扎与模型显式配置的 fail-fast 在 fenix-model-config 侧执行（它是
 * headless-runner 的注入依赖，失败即 StartupError exit 1）。
 */

import { registerTaskTools } from "./taskTools.ts";
import { registerGuards } from "./guards.ts";
import { apply as verifyApproval } from "./approval.ts";
import { assertDshPinned } from "./version.ts";

export const name = "fenix-dsh-bundle";

/** 依赖 fenixModelConfig（fail-fast 链）与 tools（注册 Task 工具族所需的服务访问）。 */
export const inject = ["fenixModelConfig", "tools"];

/** 本插件消费的 dsh 上下文面（结构最小集，避免直接依赖 cordis 类型）。 */
interface FenixBundleContext {
  tools: { register(definition: unknown): unknown };
  on(
    event: "tools/pre-execute",
    listener: (exec: unknown, next: () => Promise<unknown>) => Promise<unknown>,
    options?: { prepend?: boolean },
  ): unknown;
  get(name: string): unknown;
}

/**
 * 插件入口：注册 Task 工具族（TaskCreate/TaskUpdate/TaskGet/TaskList）与三守卫
 * （主树写 / 读图 / 场景批处理），并校验审批策略处于无人值守安全值。
 */
export function apply(ctx: FenixBundleContext): void {
  assertDshPinned();
  registerTaskTools(ctx);
  registerGuards(ctx);
  verifyApproval(ctx);
}
