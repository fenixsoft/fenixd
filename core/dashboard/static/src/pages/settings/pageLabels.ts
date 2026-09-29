// 页签 key → 标签 单一来源（code-review item e0b8f3aefec7）：供
// settings/index 与 SyncFromUserButton 等子组件复用，避免手工副本漂移。
// 无依赖共享模块（code-review item 6df16f377728）：旧位置在 settings/index.tsx，
// 子组件从 index 反向导入形成模块循环（index → panels → button → index）。
// as const（code-review item 32ab875ddc2e）：静态消费点（PAGE_LABELS.xxx）拼错
// 键名直接编译报错，不再被 Record<string, string> 吞掉、运行时渲染空标签。
export const PAGE_LABELS = {
  llm: '模型',
  agents: '模型分配',
  prompts: '提示词',
  parallel: '并行',
  token: '预算',
  verify: '验证',
  quality: '质量',
  approval: '审批',
  misc: '归档',
  system: '系统',
  'self-evolution': '自进化',
  'self-review': '自省',
  'project-profile': '项目',
  hook: 'Hook',
} as const;

/** 全部页签 key 的联合（动态索引方按 Partial<Record<PageKey, string>> 收窄） */
export type PageKey = keyof typeof PAGE_LABELS;
