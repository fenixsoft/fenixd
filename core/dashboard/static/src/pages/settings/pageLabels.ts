// 页签 key → 消息目录键 单一来源（code-review item e0b8f3aefec7）：供
// settings/index 与 SyncFromUserButton 等子组件复用，避免手工副本漂移。
// 无依赖共享模块（code-review item 6df16f377728）：旧位置在 settings/index.tsx，
// 子组件从 index 反向导入形成模块循环（index → panels → button → index）。
// as const（code-review item 32ab875ddc2e）：静态消费点（PAGE_LABELS.xxx）拼错
// 键名直接编译报错，不再被 Record<string, string> 吞掉、运行时渲染空标签。
//
// add-framework-i18n-zh-en 3.3：值改承载 src/locales/ 消息目录键（zh 文案单源
// 在 zh-CN.ts，enOverrides 补英文、缺键运行时回退中文）——消费点渲染期
// formatMessage 展开（getIntl/useIntl），语言切换即时生效。本数组仍是
// 「页签 key ↔ 目录键」的唯一配对源。
export const PAGE_LABELS = {
  llm: 'settings.tab.llm',
  agents: 'settings.tab.agents',
  prompts: 'settings.tab.prompts',
  parallel: 'settings.tab.parallel',
  token: 'settings.tab.token',
  verify: 'settings.tab.verify',
  quality: 'settings.tab.quality',
  approval: 'settings.tab.approval',
  // misc 键为历史遗留，勿按字面「杂项」理解：页签原为「其他」杂项段，
  // add-spec-archive（1ccca2fc）将其更名「归档」后键名保留未迁——键同时是
  // 后端 _SYNC_PAGE_KEYS（config_admin.py）的同步页标识，改名牵动后端契约。
  // 现语义为「归档 + 真相源」页签（archive 与 knowledge 同步键均挂 misc）。
  misc: 'settings.tab.misc',
  system: 'settings.tab.system',
  // 2026-11-28 用户指令：自动更新页签自运维页迁入设置页（运维页职责是「基于
  // fenix 框架开发的工程」的运维，fenix 自身更新归设置页）。面板独立于配置
  // 守卫渲染（状态读 ~/.fenix/update/status.json，不参与 GET/PUT /api/config，
  // 同 interface/prompts 口径），也不在 _SYNC_PAGE_KEYS 同步契约内。
  update: 'settings.tab.update',
  'self-evolution': 'settings.tab.selfEvolution',
  // add-arbiter-lane：全局决策者车道页签；处置链面板原为独立「处置链」页签
  // （add-escalation-chain-admin-arbiter 5.3），后并入本页签堆叠呈现，chain 键
  // 已随菜单项一并移除（面板自带「处置链」标题，页签内自解释）
  arbiter: 'settings.tab.arbiter',
  // 2026-11-26 用户指令：「界面风格」「界面语言」合并为「界面」页签，置于菜单首位
  // （BASE_MENU_ITEMS 第一项）；theme/locale 两键随之移除——浏览器本地偏好，
  // 无后端契约消费方，可安全改名；不参与 PUT /api/config 保存路径与后端 同步契约。
  interface: 'settings.tab.interface',
  'self-review': 'settings.tab.selfReview',
  'project-profile': 'settings.tab.projectProfile',
  hook: 'settings.tab.hook',
} as const;

/** 全部页签 key 的联合（动态索引方按 Partial<Record<PageKey, string>> 收窄） */
export type PageKey = keyof typeof PAGE_LABELS;
