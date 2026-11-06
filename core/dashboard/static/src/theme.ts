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

/** dsw static-neutral-bluish-50：布局 chrome 底色档（2026-11-06 用户指令
 * 「菜单、标题栏、Fenix Harness 标题背景 rgb(249,250,251)」后升格）——表格表头 /
 * 轻底纹 / 侧栏菜单 / 标题栏玻璃染色 rgb 通道全部取本值。 */
export const DSH_BG_SOFT = '#f9fafb';
/** 行壳位玻璃底（embed 档标题带）：上值 60% 透明形态，配 backdrop-filter
 * blur(8px) 使用。rgb 通道必须与 DSH_BG_SOFT 同源共改（pageTitleBar 守卫测试
 * 钉住通道一致与透明度必须保留——毛玻璃生效前提=底半透明，回实底即静默失效）。
 * （2026-11-06 用户指令「标题栏只是改变颜色，保留毛玻璃」：当日早前误改实底，
 * 本值恢复并确认保留。） */
export const DSH_BG_SOFT_GLASS = 'rgba(249, 250, 251, 0.6)';
/** standalone 顶栏玻璃底（2026-11-06 用户指令「标题栏只换染色保留毛玻璃」）：
 * pro-layout fixedHeader 缺省 rgba(255,255,255,0.4) 的 soft 染色形态，alpha 0.4
 * 同档只换 rgb 通道；blur 由 pro-layout 顶栏样式内置（blur(8px)+-webkit-），
 * 无需另配。 */
export const DSH_HEADER_GLASS = 'rgba(249, 250, 251, 0.4)';
/** standalone 顶栏滚动态玻璃底：-fixed-header-scroll 类换底档，缺省
 * rgba(255,255,255,0.8) 的 soft 染色形态。漏配则滚动态顶栏回白。 */
export const DSH_HEADER_GLASS_SCROLL = 'rgba(249, 250, 251, 0.8)';
/** dsw alias-bg-module-platform（neutral-bluish-60）：行 hover / 中性填充档。 */
export const DSH_BG_MODULE = '#f5f6f7';
/** SPEC 列表页移动端（<768px）内容区背景 #e3e3e3：2026-11-06 用户原型批注
 * 指定色值（add-spec-list-mobile-style design 偏离声明段），不在宪法 token 表
 * 内的已登记偏离色——DESIGN.md 一般域「SPEC 列表页移动端内容区背景」修正案
 * 条款收口。消费点仅 SPEC 列表页移动端内容区，桌面零改动。 */
export const SPEC_LIST_MOBILE_BG = '#e3e3e3';

/** dsw alias-interactive-bg-hover（#2631480f）：侧栏行 hover 冷灰。 */
export const DSH_INTERACTIVE_HOVER = 'rgba(38, 49, 72, 0.06)';
/** 数据行活动底：蓝调 rgb(99 136 211 / 10%)（2026-11-04 用户裁决；原为 dsw
 *  alias-interactive-bg-active 侧栏行选中冷灰 #2631481a，改值后不再等值该别名）。 */
export const DSH_INTERACTIVE_ACTIVE = 'rgb(99 136 211 / 10%)';

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
  header: {
    // 顶栏玻璃染色换 soft（2026-11-06 用户指令两段：先「菜单、标题栏、Fenix
    // Harness 标题背景 rgb(249,250,251)」，后更正「标题栏只是改变颜色，保留
    // 毛玻璃」）——pro-layout fixedHeader 顶栏缺省白染毛玻璃
    // （rgba(255,255,255,0.4/0.8) + 内置 blur(8px)）只换 rgb 通道为 soft，
    // alpha 双档不变；Fenix Harness 品牌区随顶栏同底（GlobalHeader transparent）。
    // **colorBgScrollHeader 必须随配**：fixedHeader 滚动超过 56px 时滚动态类名
    // （-fixed-header-scroll）换底，漏配即滚动态回白染色。顶栏下边框（pro-layout
    // header borderBlockEnd）与侧栏右边框（sider-children borderInlineEnd）同为
    // colorSplit=DSH_SPLIT，「标题栏下边框与菜单右边框一致可见」由两处同取
    // colorSplit 成立，勿局部覆写。
    colorBgHeader: DSH_HEADER_GLASS,
    colorBgScrollHeader: DSH_HEADER_GLASS_SCROLL,
  },
  sider: {
    // 侧栏（菜单）底色同批改 soft（pro-layout 缺省侧栏底 = antd lightSiderBg =
    // colorBgContainer 白）；同键兼作侧栏 Menu 的 itemBg/subMenuItemBg，与容器
    // 同色即菜单行与侧栏平涂一体。
    colorMenuBackground: DSH_BG_SOFT,
  },
  pageContainer: {
    paddingInlinePageContainerContent: 15,
    // unified-page-title-bar 3.2 实拍回校：页头摘除（pageHeaderRender={false}）
    // 后 children-container 落 no-header 变体，paddingBlockStart 以本键回填
    // pro-layout 缺省 32px——页头时代的「页头↔内容」顶带遗留，统一标题栏接管
    // 页面标识后归零（定高页 settings/help calc(100vh - 顶栏 56) 才能贴底不出
    // 第二滚动条）。底部呼吸带随同键收零：滚动页（overview 等）底缘由内容
    // 自身 margin 承担。PagePlaceholder 豁免页页头块向间距派生自本键（/4、/2
    // 档），一并归零属可接受观感变化（占位页低视觉要求）。
    paddingBlockPageContainerContent: 0,
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
