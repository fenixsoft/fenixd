// 模型分配编辑器的值模型与纯工具函数。
// 抽到独立 .ts（非 .tsx）以便 node --test 直接加载做单元测试。

export interface ChainRow {
  provider: string;
  model: string;
}

export interface RoleValue {
  roleModel: string;
  rows: ChainRow[];
}

// 深拷贝一份角色配置：复制到剪贴板、从剪贴板粘贴回卡片都经此归一。
// 深拷贝保证之后编辑卡片（含 rows 增删改）不会引用串改已复制的内容。
export function cloneRoleValue(value?: RoleValue): RoleValue {
  return {
    roleModel: value?.roleModel ?? '',
    rows: (value?.rows ?? []).map((r) => ({ provider: r.provider, model: r.model })),
  };
}
