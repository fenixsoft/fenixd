// 质量门禁渲染语义映射（add-quality-gates-visibility 任务 4.2/4.3）。
//
// node:test 原生 type-stripping 只能加载 .ts 不能加载 .tsx，六态→渲染语义的
// 映射判断抽到此纯函数模块（零 import，node 与 Vite 双端可直接加载），
// detail.tsx 只做 JSX 套用；qualityGates.test.mjs 直接对本模块断言。
//
// 六态渲染语义（spec 任务 4.2 固化）：
//   passed   勾选 + 删除线
//   failed   红色文字 + detail 归因辅助文案
//   running  「进行中」标识
//   pending  灰色
//   skipped  勾选 +「不适用」标识（勾选样式与 passed 区分：不加删除线）
//   unknown  「无记录」灰色

// 门禁橙（spec 任务 4.2 指定色）：详情页进度条描边（与列表页 progressPhase.ts
// 的 GATES_STROKE 同值——两模块零 import 自包含，node 加载要求，勿合并）
export const GATES_STROKE = '#fa8c16';

export type GateItem = {
  id: string;
  desc: string;
  status: string;
  detail?: string;
};

// items 容错归一：非数组 → 空数组；项非对象剔除；缺字段补默认值——未知
// gate-id / 异常形状不崩（任务 4.3），渲染前统一过此归一。
export function normalizeGateItems(items: unknown): GateItem[] {
  if (!Array.isArray(items)) return [];
  return items
    .filter((it): it is Record<string, unknown> => !!it && typeof it === 'object')
    .map((it) => {
      const id = it.id != null ? String(it.id) : '';
      return {
        id,
        desc: it.desc != null ? String(it.desc) : id,
        status: it.status != null ? String(it.status) : 'unknown',
        ...(it.detail != null ? { detail: String(it.detail) } : {}),
      };
    });
}

// 计入完成度的两态：passed 与 skipped（不适用=已了结；后端 done 同口径含 skipped）
export function gateCounted(item: GateItem): boolean {
  return item.status === 'passed' || item.status === 'skipped';
}

// 勾选框视觉：passed 与 skipped 都勾（skipped 勾选表示该门已了结而非通过，
// 以「不适用」后缀 + 无删除线区分）
export function gateChecked(item: GateItem): boolean {
  return gateCounted(item);
}

// 删除线：仅 passed——「不适用」不是「已完成」
export function gateStrikeThrough(item: GateItem): boolean {
  return item.status === 'passed';
}

// 文字颜色：failed 红、pending/unknown 灰、其余默认
export function gateTextColor(item: GateItem): string | undefined {
  if (item.status === 'failed') return '#cf1322';
  if (item.status === 'pending' || item.status === 'unknown') return '#999';
  return undefined;
}

// 状态后缀标识：running/skipped/unknown 各有文案，其余空串
export function gateSuffix(item: GateItem): string {
  if (item.status === 'running') return '（进行中）';
  if (item.status === 'skipped') return '（不适用）';
  if (item.status === 'unknown') return '（无记录）';
  return '';
}

// 辅助文案：detail 透传（failed 归因原文 / passed 通过失败计数 / skipped 不适用
// reason）；running 不渲染——其状态由「进行中」后缀承载，detail 为同义文案
export function gateDetailText(item: GateItem): string {
  if (item.status === 'running') return '';
  return item.detail || '';
}

// Card 渲染条件（任务 4.2）：drafted/ready 且无门禁文件 → 不渲染本 Card；
// 其余状态恒渲染（文件不可见时由调用方直接渲染「暂无质量门禁记录」空态文案）
export function shouldRenderGatesCard(
  status: string | null | undefined,
  exists: boolean,
): boolean {
  if (!exists && (status === 'drafted' || status === 'ready')) return false;
  return true;
}
