// 列表「任务进度」列阶段映射（add-quality-gates-visibility 任务 5.1/5.2）。
//
// node:test 原生 type-stripping 只能加载 .ts 不能加载 .tsx，阶段→完成度/配色
// 的映射抽到此纯函数模块（零 import，node 与 Vite 双端可直接加载）；
// list.tsx 原地 import 替换本地定义，调用点零改动（impl/verify 分支行为由
// qualityGates.test.mjs 的零回归用例钉住）。

export const TRACK_LIGHT = '#e6f4ff'; // antd blue-1，与 #1677ff 同 ramp
export const TRACK_GREEN = 'rgb(225, 236, 215)'; // 淡绿底轨（用户指定色），verify 阶段空条可辨
// 淡青底轨（antd cyan-1，与出题青 #13c2c2 同 ramp）：verify 出题态空条可辨
export const TRACK_CYAN = '#e6fffb';
// 门禁橙（spec 任务 5.1 指定色）：gates 阶段进度条描边
export const GATES_STROKE = '#fa8c16';
// 淡橙底轨（antd orange-1，与 #fa8c16 同 ramp）：gates 阶段空条可辨
export const GATES_TRAIL = '#fff7e6';

// 结构化参数（与 SpecSummary 字段子集对齐；用局部类型而非 import，保住
// node type-stripping 的零解析加载）
export type PhaseRecord = {
  progress_phase?: 'verify' | 'impl' | 'gates' | null;
  task_done: number;
  task_total: number;
  verify_done: number;
  verify_total: number;
  gates_done?: number;
  gates_total?: number;
};

export function pct(done: number, total: number): number {
  // 统一钳制 0-100：后端计数漂移（done > total）时不让排序键与进度条超出
  return total > 0 ? Math.max(0, Math.min(100, Math.round((done / total) * 100))) : 0;
}

// gates 阶段用门禁完成度（done 含 skipped——后端 done 同口径），verify 阶段
// 用验证完成度，其余 impl 阶段用任务完成度（「显示什么按什么排」，列 sorter
// 与渲染共用本函数，排序键自动跟随）。
export function phasePct(record: PhaseRecord): number {
  if (record.progress_phase === 'gates') {
    return pct(record.gates_done ?? 0, record.gates_total ?? 0);
  }
  if (record.progress_phase === 'verify') return pct(record.verify_done, record.verify_total);
  return pct(record.task_done, record.task_total);
}

// 任务进度列的渲染百分比（ocr 收尾审查 finding#1：具名函数替代嵌套三元，
// ca92db5ea623 先例）。gen 仅 verify 阶段出现：执行未开始时进度条展示出题进度。
export function renderPercent(
  record: PhaseRecord,
  gen: { done: number; total: number } | null,
): number {
  if (record.progress_phase === 'gates') return phasePct(record);
  if (record.progress_phase === 'verify') {
    return gen ? pct(gen.done, gen.total) : pct(record.verify_done, record.verify_total);
  }
  return pct(record.task_done, record.task_total);
}

// 进度条配色（code-review item ca92db5ea623 先例：具名函数替代嵌套三元）：
// 出题青 > 门禁橙 > verify 绿 > impl 蓝（gen 仅 verify 阶段出现，优先级只防
// 误用，实际互斥）。
export function strokeColorFor(gen: boolean, isVerify: boolean, isGates = false): string {
  if (gen) return '#13c2c2';
  if (isGates) return GATES_STROKE;
  return isVerify ? '#52c41a' : '#1677ff';
}

// 底轨随阶段同 ramp：gates 淡橙、verify 淡绿、impl 淡蓝、出题淡青，0/0 空条读得出阶段
export function trailColorFor(gen: boolean, isVerify: boolean, isGates = false): string {
  if (isGates) return GATES_TRAIL;
  if (!isVerify) return TRACK_LIGHT;
  return gen ? TRACK_CYAN : TRACK_GREEN;
}
