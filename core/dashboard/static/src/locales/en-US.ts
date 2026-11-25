// en-US.ts — Dashboard 英文文案目录（add-framework-i18n-zh-en 1.2 / design D3）。
//
// **spread 底座回退契约**（design D3）：导出 `{ ...zhCN, ...enOverrides }`——
// 未翻译键自动回落中文，运行时永不出现键名裸露（dashboard-i18n
// 「未覆盖键回退中文不裸露键名」Scenario）。enOverrides 键集 MUST ⊆
// zh-CN 键集，tests/localePreference.test.mjs 静态断言（防拼写漂移）。
// 术语对照表见 zh-CN.ts 文件头注释（目录内单点承载）。
import zhCN from './zh-CN.ts';

/**
 * en 覆写集：仅登记已完成翻译的键。新增键先落 zh-CN.ts（回退源），
 * 翻译完成后在本对象补同键英文覆写。
 */
export const enOverrides: Record<string, string> = {
  // ── 侧栏菜单与页题链路 ──
  'menu.overview': 'Overview',
  'menu.projects': 'Projects',
  'menu.settings': 'Config',
  'menu.ops': 'Ops',
  'menu.commandCenter': 'Command Center',
  'menu.help': 'Help',

  // ── 通用动作 ──
  'common.ok': 'OK',
  'common.cancel': 'Cancel',
  'common.close': 'Close',
  'common.save': 'Save',
  'common.delete': 'Delete',
  'common.edit': 'Edit',
  'common.refresh': 'Refresh',
  'common.retry': 'Retry',
  'common.copy': 'Copy',
  'common.search': 'Search',
  'common.reset': 'Reset',
  'common.more': 'More',
  'common.loading': 'Loading…',
  'common.confirmTitle': 'Confirm',

  // ── 通用状态 ──
  'common.status.unknown': 'Unknown',
  'common.status.running': 'Running',
  'common.status.success': 'Success',
  'common.status.failed': 'Failed',
  'common.status.pending': 'Pending',
  'common.error': 'Error',

  // ── 通用空态 ──
  'common.empty.default': 'No data yet',
  'common.empty.noResults': 'No matching results',

  // 注意：common.actions 有意不覆写——「en 缺键回退中文」契约活样例
  // （zh-CN.ts 内注释与 tests/localePreference.test.mjs 抽查断言）。

  // ── 配置页「界面语言」面板 ──
  'settings.locale.tab': 'Language',
  'settings.locale.title': 'Language',
  'settings.locale.desc':
    'Applies immediately and is stored in your browser (not written to config files). The system option follows your browser language.',
  'settings.locale.option.system': 'System',
  'settings.locale.option.systemHint': 'Follow the browser language (default)',
  'settings.locale.option.zh': '中文',
  'settings.locale.option.zhHint': 'Fixed Simplified Chinese (zh-CN)',
  'settings.locale.option.en': 'English',
  'settings.locale.option.enHint': 'Fixed English (en-US); uncovered text falls back to Chinese',
};

const enUS: Record<string, string> = { ...zhCN, ...enOverrides };

export default enUS;
