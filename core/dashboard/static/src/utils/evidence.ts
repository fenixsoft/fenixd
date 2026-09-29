// 告警证据渲染归一（fix-alert-evidence-render-crash）。
//
// 后端 admin_alerts.json 的 evidence 契约是字符串（admin_store 写/读两侧已
// 归一），但历史记录里可能残留结构化值（dict/list）。React 直接把对象当子
// 节点渲染会整页崩溃："Objects are not valid as a React child (found: object
// with keys {conflict_files, stash_kept, ...})"。任何证据渲染前都过这道归一，
// 保证拿到的是可渲染字符串。
export function fmtEvidence(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    // 循环引用等不可序列化对象：降级为 String()，绝不抛异常打断渲染
    return String(value);
  }
}
