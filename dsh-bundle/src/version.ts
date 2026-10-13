/**
 * version.ts — Bundle 版本钉扎（add-fenix-dsh-bundle：peer 钉 dsh 0.2.0-rc.2，升级走独立 SPEC）。
 *
 * 双层防线：
 * 1. package.json peerDependencies 精确钉版 —— dsh 的 bundle 兼容检查
 *    （dsh-app-boot evaluatePluginCompatibility）在安装期拒绝、装载期跳过并告警；
 * 2. 本模块的 assertDshPinned 在插件 apply 内再校验一次运行时版本 —— 抛错即
 *    fenix-model-config fiber 失败 → 依赖链上的 headless-runner（required 条目）
 *    一起失败 → StartupError exit 1（对「peer 检查被豁免/绕过」的场景兜底）。
 */

import { getDshRuntimeVersion } from "@deepseek-ai/dsh-app-boot";

/** 唯一支持的 dsh 运行时版本（与 package.json peerDependencies 逐字一致）。 */
export const PINNED_DSH_VERSION = "0.2.0-rc.2";

/**
 * 断言当前 dsh 运行时版本与钉扎版本一致；不一致抛明确版本错误（fail-fast，
 * 不静默降级）。
 */
export function assertDshPinned(runtimeVersion: string = getDshRuntimeVersion()): string {
  if (runtimeVersion !== PINNED_DSH_VERSION) {
    throw new Error(
      `fenix-dsh-bundle 版本钉扎不满足：要求 dsh ${PINNED_DSH_VERSION}，当前运行时 ${runtimeVersion}。` +
        `请在与之兼容的 dsh 上挂载本 Bundle，或走独立 SPEC 升级钉扎（不静默降级）。`,
    );
  }
  return runtimeVersion;
}
