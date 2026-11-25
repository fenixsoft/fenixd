// zh-CN.ts — Dashboard 中文文案目录（add-framework-i18n-zh-en 1.2 / design D3）。
//
// Umi Max locale 插件约定路径（config.ts locale.default 指向本文件）：
// 全站界面静态文案的唯一中文来源，键命名 `<域>.<页/组件>.<语义键>`。
// 域前缀划分：menu.*（侧栏菜单与页题链路）、common.*（通用动作/状态/空态）、
// projects.* / settings.* / overview.* / ops.*（运维页）/ commandCenter.* /
// help.* / components.*（全局组件）/ utils.*（utils 展示映射）。
//
// **en-US 目录以本文件为缺省底座**（design D3）：en-US.ts 经
// `{ ...zhCN, ...enOverrides }` 展开导出——en 缺键运行时自动回落中文，
// 杜绝「键名裸露」。新增键 MUST 先落本文件（zh 为回退源），再补 enOverrides。
//
// **双语术语对照表**（design Risks：技术术语译法统一，验证批按表复核）：
// - SPEC：不译（present tense id，本产品双语数据基因）
// - 晋升 = promote / 回炉 = reflow / 激活 = activate / 归档 = archive
// - 处置链 = disposition chain / 仲裁 = arbiter / 自愈 = self-heal
// - 运维 = ops（本页面名，区别于「设置/Settings」= dsh 官方）
// - 配置 = Config（本品页面名，避让 dsh 官方「设置/Settings」词汇面，
//   settings-page 能力页词汇对表纪律）
// - 实现者 = implementer / 规划者 = planner / 审查者 = reviewer /
//   验证者 = verifier / 裁决者 = judge / 管理员 = administrator
const zhCN = {
  // ── 侧栏菜单与页题链路（3.1：menuDataRender / routes / document.title 三处同源）──
  'menu.overview': '概览',
  'menu.projects': '项目',
  'menu.settings': '配置',
  'menu.ops': '运维',
  'menu.commandCenter': '指挥中心',
  'menu.help': '帮助',

  // ── 通用动作 ──
  'common.ok': '确定',
  'common.cancel': '取消',
  'common.close': '关闭',
  'common.save': '保存',
  'common.delete': '删除',
  'common.edit': '编辑',
  'common.refresh': '刷新',
  'common.retry': '重试',
  'common.copy': '复制',
  'common.search': '搜索',
  'common.reset': '重置',
  'common.more': '更多',
  'common.loading': '加载中…',
  'common.confirmTitle': '操作确认',

  // ── 通用状态 ──
  'common.status.unknown': '未知',
  'common.status.running': '运行中',
  'common.status.success': '成功',
  'common.status.failed': '失败',
  'common.status.pending': '等待中',
  'common.error': '错误',

  // ── 通用空态 ──
  'common.empty.default': '暂无数据',
  'common.empty.noResults': '无匹配结果',

  // 通用动作（表格列头）：**有意未进 enOverrides**——「en 缺键回退中文」契约的
  // 活样例（tests/localePreference.test.mjs 抽查本键返回中文文案，验证 spread
  // 底座回退）。en 翻译就绪后补入 enOverrides 并同步调整该测试抽查对象。
  'common.actions': '操作',

  // ── 配置页「界面语言」面板（add-framework-i18n-zh-en 2.1/2.2）──
  'settings.locale.tab': '界面语言',
  'settings.locale.title': '界面语言',
  'settings.locale.desc':
    '界面语言立即全站生效并保存在浏览器本地（不写入配置文件）。跟随系统档随浏览器语言自动判定。',
  'settings.locale.option.system': '跟随系统',
  'settings.locale.option.systemHint': '随浏览器语言自动判定（缺省）',
  'settings.locale.option.zh': '中文',
  'settings.locale.option.zhHint': '固定简体中文（zh-CN）',
  'settings.locale.option.en': 'English',
  'settings.locale.option.enHint': '固定英文（en-US），未覆盖文案回退中文',
} as const;

export default zhCN;
