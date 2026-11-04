// theme.ts — 宿主对齐主题单源（DESIGN.md 一般域「宿主对齐基线」条款的实现面）。
//
// dsh web 面板桥（fenix-dsh-dashboard-bridge）把本前端以 iframe 铺满嵌进 dsh
// web 主面板，宿主设计语言 = DeepSeek Harness web 浅色主题。本文件把 dsh 的
// alias token 表（@deepseek-ai/dsh-client-ui-theme 0.2.0-rc.2 注入的 --dsw-*
// CSS 变量）翻译为 antd v6 ThemeConfig，供 app.tsx rootContainer 的
// ConfigProvider 消费；ProLayout 侧色（defaultSettings.colorPrimary）与本表
// 保持同值。
//
// 出处（DESIGN.md「宿主对齐基线」条款同源）：dsh-client-ui-theme lib/client.js
// alias 定义 + dsh-client-ui-primitives 基元 CSS（Button/Input/Switch/Tag/
// settings-form），2026-11-03 用户指令「dashboard 嵌入 dsh web 无割裂感」。
//
// 红线对照（DESIGN.md 配色单源红线）：界面颜色只准取自本表 / antd 语义 token，
// 组件内不散落硬编码色值；需要状态色相的字面量（如 StatusTag TONE_HEX、
// settings 提示文字）从本文件 import 常量，不另起色板。

/** dsh alias-brand-primary：neutral-bluish-1000（近黑），主按钮 / 开关 ON / 勾选 / 选中态。 */
export const DSH_PRIMARY = '#0f1115';
/** dsw alias-button-primary-hover：neutral-bluish-750。 */
export const DSH_PRIMARY_HOVER = '#43454a';
/** dsw alias-button-primary-active 的按下取色：neutral-bluish-850（比 hover 更深）。 */
export const DSH_PRIMARY_ACTIVE = '#2c2c2e';
/** dsw static-deepseek-500：alias-link / state-business-primary——蓝只留给链接、info、输入焦点。 */
export const DSH_LINK = '#4176e6';
/** dsw alias-state-success-primary：static-green-500。 */
export const DSH_SUCCESS = '#22c55e';
/** dsw alias-state-error-primary：static-red-600。 */
export const DSH_ERROR = '#ec1313';
/** dsw alias-state-warn-primary：static-amber-500。 */
export const DSH_WARNING = '#f59e0b';

/** dsw alias-label-primary（neutral-bluish-1000）。 */
export const DSH_TEXT = '#0f1115';
/** dsw alias-label-secondary（neutral-bluish-700）。 */
export const DSH_TEXT_SECONDARY = '#61666b';
/** dsw alias-label-tertiary（neutral-bluish-600）。 */
export const DSH_TEXT_TERTIARY = '#81858c';
/** dsw alias-label-caption（neutral-bluish-400）。 */
export const DSH_TEXT_CAPTION = '#adb2b8';

/** dsw alias-border-l4（黑 16% alpha）：输入框 / 卡片描边。 */
export const DSH_BORDER = 'rgba(0, 0, 0, 0.16)';
/** dsw alias-border-l2（黑 10% alpha）：次级边框。 */
export const DSH_BORDER_SECONDARY = 'rgba(0, 0, 0, 0.10)';
/** 黑 8% alpha：l1（6%）与 l2（10%）之间的分隔细线档。 */
export const DSH_SPLIT = 'rgba(0, 0, 0, 0.08)';

/** dsh 基元控件高度：Input 32px（Button md 36 / sm 28，antd 默认档对齐 Input）。 */
export const DSH_CONTROL_HEIGHT = 32;
export const DSH_CONTROL_HEIGHT_SM = 28;

/** dsw-font-family：与 global.less body 同栈（PingFang SC 等中文回退在 Roboto 之前）。 */
export const DSH_FONT_FAMILY =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif";

/** dsw static-neutral-bluish-50：表格表头 / 轻底纹档（同侧栏底色一族）。 */
export const DSH_BG_SOFT = '#f9fafb';
/** dsw alias-bg-module-platform（neutral-bluish-60）：行 hover / 中性填充档。 */
export const DSH_BG_MODULE = '#f5f6f7';
/** dsw alias-interactive-bg-hover（#2631480f）：侧栏行 hover 冷灰。 */
export const DSH_INTERACTIVE_HOVER = 'rgba(38, 49, 72, 0.06)';
/** dsw alias-interactive-bg-active（#2631481a）：侧栏行选中冷灰。 */
export const DSH_INTERACTIVE_ACTIVE = 'rgba(38, 49, 72, 0.10)';

/**
 * 菜单选中底：黑 4% alpha（2026-11-04 用户统一裁决，与 ProLayout 侧栏菜单选中
 * 底看齐——原冷灰 10% 在设置页内层菜单上显著深于侧栏，被判不统一）。帮助页
 * 目录菜单选中底同源消费。数据行选中（projects 列表行等）仍走
 * DSH_INTERACTIVE_ACTIVE，两者语义不同并存。
 */
export const DSH_MENU_SELECTED_BG = 'rgba(0, 0, 0, 0.04)';

/**
 * ProLayout 布局 token（app.tsx layout 配置的 token 键消费，ProLayout →
 * ProConfigProvider → PageContainer 全链同源）：PageContainer 内容区左右留白
 * pro-layout 默认 40px（getLayoutDesignToken 缺省）压缩为 15px（2026-11-04 用户
 * 二次裁决：首版齐平 0 过紧，回撤到窄边距）——仪表盘数据墨水优先（DESIGN.md
 * 通用条款），回收阶外空带但保留一线呼吸；PageContainer 页头标题行走同一 token
 * （paddingInline 同键），无需逐页补偿。<768 窄屏由 global.less 既有 12px 覆盖
 * 规则接管（触控目标留边），本键只改桌面口径。注意 getLayoutDesignToken 的缺省
 * 回填是 `x || 40`，0 会被吞（实际靠尾部 spread 覆盖）——改值前复核该合并行为。
 * **强耦合**：global.less 设置页卡体 `margin-right: -15px`（滚动条贴视口右缘）
 * 与本值等量抵消，改本值必须同步该负边距（两处注释互指）。
 */
export const dshLayoutToken = {
  pageContainer: {
    paddingInlinePageContainerContent: 15,
  },
} as const;

/**
 * 宿主对齐 ThemeConfig（antd v6）。根 token 承载色板 / 圆角 / 控件高度单源；
 * components 仅覆写「antd 默认与 dsh 基元不一致」的项：
 * - Input/Select 焦点 = 蓝（dsw Input.module.css focus-within = state-business-primary），
 *   悬停不加深为黑系（dsh 输入框 hover 不变框色）；
 * - Button 无阴影（dsh 基元按钮纯平涂）；
 * - Table 表头 = bluish-50 底 + 次级文字（dsw markdown-table-head 13px/500 语义）；
 * - Menu 选中 = 冷灰底 + 黑字、行高 36（dsh 侧栏行基线，bridge HEADER_ROW_HEIGHT 同源）。
 * 圆角不在覆盖范围：2026-11-03 用户裁决还原 antd 默认圆角（卡片/控件 6/4/8），
 * 不引入 dsw radius 阶（首版曾挂 12/8/16 与 Tag 胶囊 999，已撤）。
 */
export const dshAlignedTheme = {
  token: {
    colorPrimary: DSH_PRIMARY,
    colorPrimaryHover: DSH_PRIMARY_HOVER,
    colorPrimaryActive: DSH_PRIMARY_ACTIVE,
    colorLink: DSH_LINK,
    colorInfo: DSH_LINK,
    colorSuccess: DSH_SUCCESS,
    colorError: DSH_ERROR,
    colorWarning: DSH_WARNING,
    colorText: DSH_TEXT,
    colorTextSecondary: DSH_TEXT_SECONDARY,
    colorTextTertiary: DSH_TEXT_TERTIARY,
    colorTextQuaternary: DSH_TEXT_CAPTION,
    colorBgLayout: '#ffffff',
    colorBorder: DSH_BORDER,
    colorBorderSecondary: DSH_BORDER_SECONDARY,
    colorSplit: DSH_SPLIT,
    // 控件项选中/选中+hover 底（Select 选中项叠加态、Cascader/TreeSelect/
    // 日期选择选中格等消费）：antd 缺省从主色种子派生 colorPrimaryBg 族——
    // 黑主色种子下为深色阶（实测 #4f5254 / #434547，配近黑文字即「黑字黑
    // 底」，2026-11-04 用户报指挥中心筛选下拉不可读；与 11-03 help.css
    // --ant-color-primary-bg 同源陷阱、Menu itemActiveBg 同款处方）。显式
    // 压回中性浅底（与表格行 hover 同档）；组件级 optionActiveBg/
    // optionSelectedBg 只管非选中 hover/选中态，叠加态必须由本别名键承接。
    controlItemBgActive: DSH_BG_MODULE,
    controlItemBgActiveHover: DSH_BG_MODULE,
    // 圆角维持 antd 默认值（2026-11-03 用户裁决：不引入 dsw radius 阶 12/8/16，
    // 卡片与控件还原 antd 原圆角 6/4/8），MUST NOT 在此挂 borderRadius 覆写。
    controlHeight: DSH_CONTROL_HEIGHT,
    controlHeightSM: DSH_CONTROL_HEIGHT_SM,
    fontFamily: DSH_FONT_FAMILY,
  },
  components: {
    Input: {
      activeBorderColor: DSH_LINK,
      activeShadow: `0 0 0 2px rgba(65, 118, 230, 0.12)`,
      hoverBorderColor: 'rgba(0, 0, 0, 0.28)',
    },
    Select: {
      activeBorderColor: DSH_LINK,
      activeOutlineColor: 'rgba(65, 118, 230, 0.12)',
      hoverBorderColor: 'rgba(0, 0, 0, 0.28)',
      // 选项 hover/选中底（2026-11-04 用户报指挥中心筛选下拉「黑字黑底看
      // 不清」）：antd 缺省走 controlItemBgHover / colorPrimaryBg 派生族——
      // 黑主色种子下派生深色阶（实测 hover 底 #43454a 级）配近黑
      // optionSelectedColor=黑字黑底，同 darkSeedBgToken 陷阱、Menu
      // itemActiveBg 显式给值同款处方。压回中性浅底（与表格行 hover 同档），
      // 选中字色随 DSH_TEXT 不另起。
      optionActiveBg: DSH_BG_MODULE,
      optionSelectedBg: DSH_BG_MODULE,
      optionSelectedColor: DSH_TEXT,
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
    },
    Table: {
      headerBg: DSH_BG_SOFT,
      headerColor: DSH_TEXT_SECONDARY,
      headerSplitColor: 'transparent',
      rowHoverBg: DSH_BG_MODULE,
    },
    Menu: {
      itemHeight: 36,
      // 选中底与侧栏看齐（DSH_MENU_SELECTED_BG 注释有裁决记录）。hover/pressed
      // 同族黑 alpha 分档（3%/6%）；itemActiveBg 必须显式给值——antd 缺省按压底
      // 走主色派生族，暗主色种子下为深色阶（同 darkSeedBgToken.test.mjs 陷阱）。
      itemSelectedBg: DSH_MENU_SELECTED_BG,
      itemSelectedColor: DSH_TEXT,
      itemHoverBg: 'rgba(0, 0, 0, 0.03)',
      itemActiveBg: 'rgba(0, 0, 0, 0.06)',
    },
  },
} as const;
