// 模型分配编辑器的值模型与纯工具函数。
// 抽到独立 .ts（非 .tsx）以便 node --test 直接加载做单元测试。

// 注意（code-review item c0afb2885437）：下方 cloneRoleValue 对 rows 逐字段拷贝
// （显式列举本接口字段），本接口新增字段时须同步维护该拷贝清单，否则剪贴板
// 复制/粘贴回的卡片会静默丢失新字段且无编译期报错。
export interface ChainRow {
  provider: string;
  model: string;
}

export interface RoleValue {
  /** 后端角色 key（agents.models 键）：表单行与后端键按此映射，不依赖下标
   * （code-review item 042e1dc46cb4——顺序/长度漂移时下标映射会静默写错键）。 */
  roleKey?: string;
  roleModel: string;
  rows: ChainRow[];
}

// 深拷贝一份角色配置：复制到剪贴板、从剪贴板粘贴回卡片都经此归一。
// 深拷贝保证之后编辑卡片（含 rows 增删改）不会引用串改已复制的内容。
// roleKey 仅在源上有值时携带（避免 undefined 键改变既有 deepEqual 语义）。
export function cloneRoleValue(value?: RoleValue): RoleValue {
  const copy: RoleValue = {
    roleModel: value?.roleModel ?? '',
    rows: (value?.rows ?? []).map((r) => ({ provider: r.provider, model: r.model })),
  };
  if (value?.roleKey !== undefined) copy.roleKey = value.roleKey;
  return copy;
}
