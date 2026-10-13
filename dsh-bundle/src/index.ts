/**
 * index.ts — fenix-dsh-bundle 装配入口（Task 工具族 + 三守卫 + 审批校验）。
 *
 * Bundle 是「数据包」：package.json 的 dsh.bundle.patch 指向 cordis.patch.yml，
 * patch 行引用本模块（fenix-dsh-bundle）与 ./modelConfig（fenix-model-config）。
 * 版本钉扎与模型显式配置的 fail-fast 在 fenix-model-config 侧执行（它是
 * headless-runner 的注入依赖，失败即 StartupError exit 1）。
 */

import { registerTaskTools } from "./taskTools.ts";
import { registerGuards, type PreToolExec, type PreToolDecision } from "./guards.ts";
import { registerAgentsMdSection, type AgentsMdContext } from "./agentsMd.ts";
import { apply as verifyApproval } from "./approval.ts";
import { assertDshPinned } from "./version.ts";

export const name = "fenix-dsh-bundle";

/**
 * 依赖声明：fenixModelConfig（fail-fast 链）、tools（注册 Task 工具族所需的
 * 服务访问）、approval（apply 链内 verifyApproval 经 ctx.get 惰性读取的策略
 * 面——ctx.get 本身无 inject 要求，但显式声明后服务必已装配，与 cordis.patch.yml
 * 的 entry 级 inject: [..., approval] 保持一致）。systemPrompt 不在此列：
 * registerAgentsMdSection 经 ctx.inject(["systemPrompt"], fn) 消费，那本身就是
 * 声明式依赖（回调仅在服务可用时执行），顶层声明只会徒增装配门控。
 */
export const inject = ["fenixModelConfig", "tools", "approval"];

/** 本插件消费的 dsh 上下文面（结构最小集，避免直接依赖 cordis 类型）。 */
interface FenixBundleContext extends AgentsMdContext {
  tools: { register(definition: unknown): unknown };
  on(
    event: "tools/pre-execute",
    listener: (exec: PreToolExec, next: () => Promise<PreToolDecision>) => Promise<PreToolDecision>,
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
  registerAgentsMdSection(ctx);
  verifyApproval(ctx);
}
