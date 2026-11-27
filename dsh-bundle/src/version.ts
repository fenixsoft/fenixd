/**
 * version.ts — Bundle dsh 运行时兼容下限（2026-11-26 用户指令：钉扎改下限制）。
 *
 * 语义：**只拒下限之下**——等于下限或更高（含更高 rc 与正式版）一律接手；
 * 与 dsh_adapter 侧 DSH_MIN_VERSION（core/agent_runner/harness/dsh_adapter.py）
 * 同一下限口径，双侧漂移由测试钉住（见 dsh-bundle/tests/version.test.ts）。
 *
 * 双层防线：
 * 1. package.json peerDependencies `>=<下限>` —— dsh 的 bundle 兼容检查
 *    （dsh-app-boot evaluatePluginCompatibility）在安装期拒绝低于下限的宿主；
 * 2. 本模块的 assertDshCompatible 在插件 apply 内再校验一次运行时版本 ——
 *    低于下限抛错即 fenix-model-config fiber 失败 → 依赖链上的 headless-runner
 *    （required 条目）一起失败 → StartupError exit 1（对「peer 检查被豁免/绕过」
 *    的场景兜底）。
 *
 * 历史注记：add-fenix-dsh-bundle 最初为逐字精确钉扎（=0.2.2-rc.1）；实测 dsh
 * rc 线迭代快（rc.1 之后即有 rc.5），精确钉扎导致每次 dsh 升级都全链拒绝，
 * 2026-11-26 起改为下限制（升级仍走独立 SPEC 评估，但运行时不逐字拒新）。
 */

import { getDshRuntimeVersion } from "@deepseek-ai/dsh-app-boot";

/** 最低兼容的 dsh 运行时版本（peerDependencies `>=` 该值；下限及以上一律接手）。 */
export const MIN_DSH_VERSION = "0.2.2-rc.1";

/**
 * semver 前序比较（含 `-rc.N` 预发布段；遵循 semver：同主.min.patch 下
 * 正式版 > 预发布，rc 段按数值比较）。返回负数/0/正数。
 *
 * 仅覆盖本仓出现的形态 `X.Y.Z` 与 `X.Y.Z-rc.N`；其余形态按解析失败抛错
 * （fail-fast，不做宽松猜测）。
 */
export function compareDshVersion(a: string, b: string): number {
  const parse = (v: string) => {
    const m = /^(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$/.exec(v);
    if (!m) throw new Error(`无法解析的 dsh 版本号形态：${v}`);
    return {
      triple: [Number(m[1]), Number(m[2]), Number(m[3])] as const,
      // 正式版用有限可序化数值表达（Number.MAX_SAFE_INTEGER 而非 Infinity），
      // 避免两个相同正式版相减得 NaN、违反「返回负数/0/正数」契约。
      rc: m[4] === undefined ? Number.MAX_SAFE_INTEGER : Number(m[4]),
    };
  };
  const pa = parse(a);
  const pb = parse(b);
  for (let i = 0; i < 3; i++) {
    if (pa.triple[i] !== pb.triple[i]) return pa.triple[i] - pb.triple[i];
  }
  // 三段一致：正式版（rc=Number.MAX_SAFE_INTEGER）> 任意 rc；rc 之间按数值
  return pa.rc - pb.rc;
}

/**
 * 断言当前 dsh 运行时版本不低于兼容下限；低于下限抛明确版本错误（fail-fast，
 * 不静默降级）。等于下限或更高（含更高 rc 与正式版）通过并返回当前版本。
 *
 * 运行时版本读取本身抛错（如宿主 API 变更）时同样 fail-fast，但错误信息
 * 会带上期望下限，便于排障时定位到本 Bundle 的版本防线。
 */
export function assertDshCompatible(runtimeVersion?: string): string {
  const current = runtimeVersion ?? readDshRuntimeVersion();
  if (compareDshVersion(current, MIN_DSH_VERSION) < 0) {
    throw new Error(
      `fenix-dsh-bundle 版本下限不满足：要求 dsh >= ${MIN_DSH_VERSION}，当前运行时 ${current}。` +
        `请升级 dsh 至下限及以上（下限之上含更高 rc 与正式版均接手），或走独立 SPEC 降级适配（不静默降级）。`,
    );
  }
  return current;
}

/** 读取 dsh 运行时版本；宿主 API 抛错时转译为带期望下限的明确错误。 */
function readDshRuntimeVersion(): string {
  try {
    return getDshRuntimeVersion();
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(
      `fenix-dsh-bundle 版本下限防线无法读取 dsh 运行时版本（期望下限 ${MIN_DSH_VERSION}）：${reason}`,
    );
  }
}
