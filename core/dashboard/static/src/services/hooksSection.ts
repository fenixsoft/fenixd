/**
 * saveHooksSection —— 「重拉基底 + hooks 段整体替换」共享单源。
 *
 * 后端 /api/config 对 hooks 段是「patch 存在即整体替换」语义：保存前必须用
 * getConfig 重拉最新基底，不能用组件内 config 快照合并——快照可能已过期
 * （页面挂载/上次保存后，另一标签或 CLI 直改过 hooks），以快照合并会静默
 * 回退他处的修改。该修复原在设置页 HooksPanel（code-review item
 * 26586e4395cd）与 SPEC 详情 SpecHooksSection（code-review item bf045d7ed0b9）
 * 两处各自落地，收敛为本单源避免语义变化/修 bug 时双处漂移
 * （code-review item 7add07b1e0e8）。
 *
 * 只覆盖两处逐行同构的「重拉基底 + 合并 hooks 段」部分：合并策略以 merge
 * 传入（设置页全局段只换 global，SPEC 详情段换 specs.<spec>）；写盘动作
 * （设置页统一 onSave / 详情页 saveConfig）与 savingRef、提示等 UI 状态
 * 管理留在调用点。
 */
import { getConfig } from '@/services/dashboard';
import type { HooksConfig } from '@/services/dashboard';

export async function saveHooksSection<T>(
  project: string,
  merge: (latestHooks: HooksConfig) => HooksConfig,
  save: (patch: { hooks: HooksConfig }) => Promise<T> | T,
): Promise<T> {
  // 基底用保存前重拉的最新配置，不用组件内 config 快照（「patch 存在即
  // 整体替换」语义见文件头注释）
  const latest = await getConfig(project);
  const latestHooks: HooksConfig = latest?.hooks ?? {};
  return await save({ hooks: merge(latestHooks) });
}
