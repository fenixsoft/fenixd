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
 *
 * 运行时版本读取本身抛错（如宿主 API 变更）时同样 fail-fast，但错误信息
 * 会带上期望钉扎版本，便于排障时定位到本 Bundle 的钉扎防线。
 */
export function assertDshPinned(runtimeVersion?: string): string {
  const current = runtimeVersion ?? readDshRuntimeVersion();
  if (current !== PINNED_DSH_VERSION) {
    throw new Error(
      `fenix-dsh-bundle 版本钉扎不满足：要求 dsh ${PINNED_DSH_VERSION}，当前运行时 ${current}。` +
        `请在与之兼容的 dsh 上挂载本 Bundle，或走独立 SPEC 升级钉扎（不静默降级）。`,
    );
  }
  return current;
}

/** 读取 dsh 运行时版本；宿主 API 抛错时转译为带期望钉扎版本的明确错误。 */
function readDshRuntimeVersion(): string {
  try {
    return getDshRuntimeVersion();
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(
      `fenix-dsh-bundle 版本钉扎防线无法读取 dsh 运行时版本（期望钉扎 ${PINNED_DSH_VERSION}）：${reason}`,
    );
  }
}
