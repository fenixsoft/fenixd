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
/** 焦点光晕：DSH_LINK 的 12% alpha 衍生档，Input.activeShadow 与
 * Select.activeOutlineColor 单源消费。rgb 通道由 parseInt 拆 DSH_LINK 的 hex
 * 现算派生——改链接蓝时两处焦点光晕随动不脱钩（对齐 DSH_BG_SOFT ↔
 * DSH_BG_SOFT_GLASS 的「同源共改」口径，且由代码派生强制而非注释约定）。 */
export const DSH_LINK_FOCUS_GLOW = `rgba(${parseInt(DSH_LINK.slice(1, 3), 16)}, ${parseInt(DSH_LINK.slice(3, 5), 16)}, ${parseInt(DSH_LINK.slice(5, 7), 16)}, 0.12)`;
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
/** dsw alias-border-l3（黑 12% alpha，#0000001f）：l2 与 l4 之间档——dsh 侧栏
 * 「新会话」按钮描边（DshNewSessionButton 单点消费，样式对齐 dsh-client-ui-sidebar
 * newSession 类）。 */
export const DSH_BORDER_L3 = 'rgba(0, 0, 0, 0.12)';
/** dsw alias-border-l2（黑 10% alpha）：次级边框。 */
export const DSH_BORDER_SECONDARY = 'rgba(0, 0, 0, 0.10)';
/** 黑 8% alpha：l1（6%）与 l2（10%）之间的分隔细线档。 */
export const DSH_SPLIT = 'rgba(0, 0, 0, 0.08)';

/** dsh 浅色档页面最外层基底（body/colorBgLayout 档）：DSH_BG_BASE_DARK 浅档
 * 对位（DSH_LIGHT.bgBase 与 dshAlignedTheme.token.colorBgLayout 单源共同
 * 消费，code-review item f0daab05c835）。 */
export const DSH_BG_BASE = '#ffffff';
/** dsw alias-button-elevated-fill（static-neutral-bluish-00 = 白）：浮起按钮底
 * ——dsh 侧栏「新会话」按钮常态底色（DshNewSessionButton 单点消费）。 */
export const DSH_BG_ELEVATED = '#ffffff';
/** dsw alias-button-floating-hover（static-neutral-bluish-75）：浮起按钮 hover 底
 * ——dsh 侧栏「新会话」按钮悬停态（DshNewSessionButton 单点消费）。 */
export const DSH_BG_FLOATING_HOVER = '#f1f3f5';

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
/** SPEC 列表页移动端（<768px）内容区背景：白底（2026-11-07 用户指令由
 * 2026-11-06 原型批注指定的 #e3e3e3 灰底改白，通用白不再属登记偏离色）——
 * DESIGN.md 一般域「SPEC 列表页移动端内容区背景」修正案条款同步收口。
 * 消费点仅 SPEC 列表页移动端内容区，桌面零改动。 */
export const SPEC_LIST_MOBILE_BG = '#ffffff';

/** dsw alias-interactive-bg-hover（#2631480f）：侧栏行 hover 冷灰。 */
export const DSH_INTERACTIVE_HOVER = 'rgba(38, 49, 72, 0.06)';
/** 数据行活动底：蓝调 rgba(99, 136, 211, 0.1)（2026-11-04 用户裁决；原为 dsw
 *  alias-interactive-bg-active 侧栏行选中冷灰 #2631481a，改值后不再等值该别名）。
 *  记法统一为文件内占多数的 rgba() 逗号形态（code-review item 47fb23481dad）。 */
export const DSH_INTERACTIVE_ACTIVE = 'rgba(99, 136, 211, 0.1)';

/**
 * 菜单选中底：黑 4% alpha（2026-11-04 用户统一裁决，与 ProLayout 侧栏菜单选中
 * 底看齐——原冷灰 10% 在设置页内层菜单上显著深于侧栏，被判不统一）。帮助页
 * 目录菜单选中底同源消费。数据行选中（projects 列表行等）仍走
 * DSH_INTERACTIVE_ACTIVE，两者语义不同并存。
 */
export const DSH_MENU_SELECTED_BG = 'rgba(0, 0, 0, 0.04)';

/**
 * 跨页共用 Bento 磁贴色值单源（code-review item b4f39b38d814 上收）：发丝边与
 * 三级文字色原在 detail.tsx / list.tsx / overview/ProjectTable.tsx 三处各自
 * 定义同值模块常量，现收本表改 import 消费。值出处仍为 2026-11-06 对齐 v2
 * 台账时的 token 表（v2 域 2026-11-07 已退役）；与 global.less `.ov-bento` /
 * `.spec-bento-card` 的镜像同步条款不变。
 */
export const OV_HAIRLINE = '#eef2f7';
export const OV_TEXT_TERTIARY = '#64748b';
/** SpecTimeline 时间轴节点磁贴卡底浅档：维持 2026-11-06 Bento 磁贴纯白底
 * （值=DSH_BG_ELEVATED 引用，无新色源；深档 TIMELINE_TILE_BG_DARK）。 */
export const TIMELINE_TILE_BG = DSH_BG_ELEVATED;
/** SpecTimeline 时间轴节点磁贴描边浅档：Bento 发丝边（值=OV_HAIRLINE 引用）。 */
export const TIMELINE_TILE_BORDER = OV_HAIRLINE;
/** 运维活动卡（activities 页自动运维/告警记录）浅档：历史字节原值
 * （#fafafa 面/#f0f0f0 边/#fff2f0+#ff4d4f 未处置错误态/#8c8c8c 空叙述兜底字）。 */
export const ACTIVITY_CARD_BG = '#fafafa';
export const ACTIVITY_CARD_BORDER = '#f0f0f0';
export const ACTIVITY_CARD_ERROR_BG = '#fff2f0';
export const ACTIVITY_CARD_ERROR_BORDER = '#ff4d4f';
export const ACTIVITY_FALLBACK_TEXT = '#8c8c8c';
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
export type ThemeScheme = 'light' | 'dark';

/**
 * 浅色档语义调色板（dashboard-dark-theme 1.1）：把上方既有浅色常量按语义收
 * 成一份记录，供按档取值助手 `dshPalette()` 与组件 hook 消费。键与常量一一
 * 对应（primary↔DSH_PRIMARY…），浅档全部引用既有常量——值单源不变。
 */
export interface DshPalette {
  primary: string;
  primaryHover: string;
  primaryActive: string;
  link: string;
  linkFocusGlow: string;
  success: string;
  error: string;
  warning: string;
  text: string;
  textSecondary: string;
  textTertiary: string;
  textCaption: string;
  border: string;
  borderL3: string;
  borderSecondary: string;
  split: string;
  bgBase: string;
  bgElevated: string;
  bgModule: string;
  bgSoft: string;
  bgSoftGlass: string;
  headerGlass: string;
  headerGlassScroll: string;
  bgFloatingHover: string;
  interactiveHover: string;
  interactiveActive: string;
  menuSelectedBg: string;
  specListMobileBg: string;
  ovHairline: string;
  ovTextTertiary: string;
  timelineTileBg: string;
  timelineTileBorder: string;
  activityCardBg: string;
  activityCardBorder: string;
  activityCardErrorBg: string;
  activityCardErrorBorder: string;
  activityFallbackText: string;
}

export const DSH_LIGHT: DshPalette = {
  primary: DSH_PRIMARY,
  primaryHover: DSH_PRIMARY_HOVER,
  primaryActive: DSH_PRIMARY_ACTIVE,
  link: DSH_LINK,
  linkFocusGlow: DSH_LINK_FOCUS_GLOW,
  success: DSH_SUCCESS,
  error: DSH_ERROR,
  warning: DSH_WARNING,
  text: DSH_TEXT,
  textSecondary: DSH_TEXT_SECONDARY,
  textTertiary: DSH_TEXT_TERTIARY,
  textCaption: DSH_TEXT_CAPTION,
  border: DSH_BORDER,
  borderL3: DSH_BORDER_L3,
  borderSecondary: DSH_BORDER_SECONDARY,
  split: DSH_SPLIT,
  bgBase: DSH_BG_BASE,
  bgElevated: DSH_BG_ELEVATED,
  bgModule: DSH_BG_MODULE,
  bgSoft: DSH_BG_SOFT,
  bgSoftGlass: DSH_BG_SOFT_GLASS,
  headerGlass: DSH_HEADER_GLASS,
  headerGlassScroll: DSH_HEADER_GLASS_SCROLL,
  bgFloatingHover: DSH_BG_FLOATING_HOVER,
  interactiveHover: DSH_INTERACTIVE_HOVER,
  interactiveActive: DSH_INTERACTIVE_ACTIVE,
  menuSelectedBg: DSH_MENU_SELECTED_BG,
  specListMobileBg: SPEC_LIST_MOBILE_BG,
  ovHairline: OV_HAIRLINE,
  ovTextTertiary: OV_TEXT_TERTIARY,
  timelineTileBg: TIMELINE_TILE_BG,
  timelineTileBorder: TIMELINE_TILE_BORDER,
  activityCardBg: ACTIVITY_CARD_BG,
  activityCardBorder: ACTIVITY_CARD_BORDER,
  activityCardErrorBg: ACTIVITY_CARD_ERROR_BG,
  activityCardErrorBorder: ACTIVITY_CARD_ERROR_BORDER,
  activityFallbackText: ACTIVITY_FALLBACK_TEXT,
};

// ════ 深色档（dashboard-dark-theme，design.md D2 映射表）══════════════════
//
// 逐项翻译自 dsh web 深色调色板（@deepseek-ai/dsh-client-ui-theme 0.2.2-rc.1
// `design_platform_css_default` 的 `body[data-ds-dark-theme]` 档，alias 语义
// 对位——出处与逐项对应关系见 design.md D2 表）。注意：本段深色常量必须置于
// 浅色常量之后（pageTitleBar 守卫以首匹配读浅档玻璃族声明，深档置后不扰动）。

/** dsh 深色档页面最外层基底（body/colorBgLayout 档）：alias bg-layer-0 同语义。 */
export const DSH_BG_BASE_DARK = '#151517';
/** dsw bg-layer-1 → bluish-875：深色卡面/输入框容器底。 */
export const DSH_BG_ELEVATED_DARK = '#232324';
/** dsw bg-module-platform → bluish-800：行 hover / 中性填充档。 */
export const DSH_BG_MODULE_DARK = '#353638';
/** dsw specific-input-major / bg-layer-2 → bluish-850：布局 chrome soft 染色通道（深档）。 */
export const DSH_BG_SOFT_DARK = '#2c2c2e';
/** bg-layer-2/3 间派生：深档浮起交互面 hover 底。 */
export const DSH_BG_FLOATING_HOVER_DARK = '#3a3b3d';
/** 深档行壳位玻璃底：DSH_BG_SOFT_DARK 60% 透明形态（soft 染色族同源共改，
 * 通道一致 + alpha<1 守卫见 themePreference.test.mjs 深色档守卫段）。 */
export const DSH_BG_SOFT_GLASS_DARK = 'rgba(44, 44, 46, 0.6)';
/** 深档 standalone 顶栏玻璃底（alpha 0.4 档位不变只换 rgb 通道）。 */
export const DSH_HEADER_GLASS_DARK = 'rgba(44, 44, 46, 0.4)';
/** 深档顶栏滚动态玻璃底（alpha 0.8 档位不变只换 rgb 通道）。 */
export const DSH_HEADER_GLASS_SCROLL_DARK = 'rgba(44, 44, 46, 0.8)';
/** dsw label-primary → bluish-50。 */
export const DSH_TEXT_DARK = '#f9fafb';
/** dsw label-secondary → bluish-300。 */
export const DSH_TEXT_SECONDARY_DARK = '#cfd3d6';
/** dsw label-tertiary → bluish-400。 */
export const DSH_TEXT_TERTIARY_DARK = '#adb2b8';
/** dsw label-caption → bluish-600。 */
export const DSH_TEXT_CAPTION_DARK = '#81858c';
/** dsw border-l1 系 alpha 反相（黑→白）：输入框 / 卡片描边。 */
export const DSH_BORDER_DARK = 'rgba(255, 255, 255, 0.16)';
/** dsw border-l3 同构反相。 */
export const DSH_BORDER_L3_DARK = 'rgba(255, 255, 255, 0.12)';
/** dsw border-l2 同构反相。 */
export const DSH_BORDER_SECONDARY_DARK = 'rgba(255, 255, 255, 0.10)';
/** 分隔细线：L3 0.12 / SECONDARY 0.10 同构反相档。 */
export const DSH_SPLIT_DARK = 'rgba(255, 255, 255, 0.08)';
/** 黑主色→白主色（dsw brand-primary → bluish-50）：主按钮白底黑字档见
 * dshAlignedThemeDark.components.Button（主色种子派生陷阱处方）。 */
export const DSH_PRIMARY_DARK = '#f9fafb';
/** dsw button-primary-hover → bluish-100。 */
export const DSH_PRIMARY_HOVER_DARK = '#ebeef2';
/** dsw button-elevated-fill → bluish-750（按下取色，比 hover 更深）。 */
export const DSH_PRIMARY_ACTIVE_DARK = '#43454a';
/** dsw link → deepseek-400。 */
export const DSH_LINK_DARK = '#7aaaff';
/** 焦点光晕深档：DSH_LINK_DARK 的 12% alpha 衍生（浅档同构代码派生，改链接
 * 蓝两处随动不脱钩）。 */
export const DSH_LINK_FOCUS_GLOW_DARK = `rgba(${parseInt(DSH_LINK_DARK.slice(1, 3), 16)}, ${parseInt(DSH_LINK_DARK.slice(3, 5), 16)}, ${parseInt(DSH_LINK_DARK.slice(5, 7), 16)}, 0.12)`;
/** dsw success：static-green-500，深浅不变。 */
export const DSH_SUCCESS_DARK = '#22c55e';
/** dsw error → red-400（浅档 red-600 #ec1313 在深底刺眼，对齐宿主降一档）。 */
export const DSH_ERROR_DARK = '#f25a5a';
/** dsw warn：static-amber-500，深浅不变。 */
export const DSH_WARNING_DARK = '#f59e0b';
/** dsw interactive-bg-hover → 白 alpha。 */
export const DSH_INTERACTIVE_HOVER_DARK = 'rgba(255, 255, 255, 0.08)';
/** dsw active #ffffff24 + link 种子 → 深档数据行活动底。 */
export const DSH_INTERACTIVE_ACTIVE_DARK = 'rgba(122, 170, 255, 0.16)';
/** dsw menu 交互系白 alpha（浅档黑 4% 反相）。 */
export const DSH_MENU_SELECTED_BG_DARK = 'rgba(255, 255, 255, 0.06)';
/** SPEC 列表页移动端内容区背景深档：bg-layer-2。 */
export const SPEC_LIST_MOBILE_BG_DARK = '#2c2c2e';
/** 跨页 Bento 磁贴发丝边深档（bg 上发丝线，浅档 #eef2f7 反相）。 */
export const OV_HAIRLINE_DARK = '#2e2f31';
/** 跨页三级文字深档（bg-module 上三级字可读档）：#adb2b8 对齐 dsh 深档
 * label-tertiary（fix-dashboard-dark-theme-ui-defects 5.1 双源校准；原 #8b8f94
 * 深底对比度不足，global.less `--fenix-ov-text-tertiary` 深档定义同批镜像）。 */
export const OV_TEXT_TERTIARY_DARK = '#adb2b8';
/** SpecTimeline 时间轴节点磁贴卡底深档（D2 同 spec-detail 卡族=bg-layer-1）。 */
export const TIMELINE_TILE_BG_DARK = DSH_BG_ELEVATED_DARK;
/** SpecTimeline 时间轴节点磁贴描边深档（白 alpha 系，同 spec-detail 卡族）。 */
export const TIMELINE_TILE_BORDER_DARK = DSH_BORDER_DARK;
/** 配置页灰底准例深档（design.md D2）：卡底 #2c2c2e、边框加深 #545557
 * （neutral-600，同「发丝线不可辨即失效」逻辑）。 */
export const SETTINGS_CARD_BG_DARK = '#2c2c2e';
export const SETTINGS_CARD_BORDER_DARK = '#545557';
/** markdown 围栏代码块深档（design.md D7：markdown-code-block #1b1b1c 系）。 */
export const MARKDOWN_CODE_BLOCK_DARK = '#1b1b1c';
/** 运维活动卡深档（2026-11-25 深色验收）：卡面=bg-layer-1 磁贴同族、描边白
 * alpha l2；未处置错误态=error #f25a5a 15% 面原值描边；兜底字=label-caption。 */
export const ACTIVITY_CARD_BG_DARK = DSH_BG_ELEVATED_DARK;
export const ACTIVITY_CARD_BORDER_DARK = 'rgba(255, 255, 255, 0.12)';
export const ACTIVITY_CARD_ERROR_BG_DARK = 'rgba(242, 90, 90, 0.15)';
export const ACTIVITY_CARD_ERROR_BORDER_DARK = DSH_ERROR_DARK;
export const ACTIVITY_FALLBACK_TEXT_DARK = DSH_TEXT_CAPTION_DARK;

export const DSH_DARK: DshPalette = {
  primary: DSH_PRIMARY_DARK,
  primaryHover: DSH_PRIMARY_HOVER_DARK,
  primaryActive: DSH_PRIMARY_ACTIVE_DARK,
  link: DSH_LINK_DARK,
  linkFocusGlow: DSH_LINK_FOCUS_GLOW_DARK,
  success: DSH_SUCCESS_DARK,
  error: DSH_ERROR_DARK,
  warning: DSH_WARNING_DARK,
  text: DSH_TEXT_DARK,
  textSecondary: DSH_TEXT_SECONDARY_DARK,
  textTertiary: DSH_TEXT_TERTIARY_DARK,
  textCaption: DSH_TEXT_CAPTION_DARK,
  border: DSH_BORDER_DARK,
  borderL3: DSH_BORDER_L3_DARK,
  borderSecondary: DSH_BORDER_SECONDARY_DARK,
  split: DSH_SPLIT_DARK,
  bgBase: DSH_BG_BASE_DARK,
  bgElevated: DSH_BG_ELEVATED_DARK,
  bgModule: DSH_BG_MODULE_DARK,
  bgSoft: DSH_BG_SOFT_DARK,
  bgSoftGlass: DSH_BG_SOFT_GLASS_DARK,
  headerGlass: DSH_HEADER_GLASS_DARK,
  headerGlassScroll: DSH_HEADER_GLASS_SCROLL_DARK,
  bgFloatingHover: DSH_BG_FLOATING_HOVER_DARK,
  interactiveHover: DSH_INTERACTIVE_HOVER_DARK,
  interactiveActive: DSH_INTERACTIVE_ACTIVE_DARK,
  menuSelectedBg: DSH_MENU_SELECTED_BG_DARK,
  specListMobileBg: SPEC_LIST_MOBILE_BG_DARK,
  ovHairline: OV_HAIRLINE_DARK,
  ovTextTertiary: OV_TEXT_TERTIARY_DARK,
  timelineTileBg: TIMELINE_TILE_BG_DARK,
  timelineTileBorder: TIMELINE_TILE_BORDER_DARK,
  activityCardBg: ACTIVITY_CARD_BG_DARK,
  activityCardBorder: ACTIVITY_CARD_BORDER_DARK,
  activityCardErrorBg: ACTIVITY_CARD_ERROR_BG_DARK,
  activityCardErrorBorder: ACTIVITY_CARD_ERROR_BORDER_DARK,
  activityFallbackText: ACTIVITY_FALLBACK_TEXT_DARK,
};

/** 按当前档取语义调色板（单源出口）：组件经 useDshPalette()（utils/themeHooks）
 * 消费本函数；scheme 由 utils/themePreference 状态机解析维护。 */
export function dshPalette(scheme: ThemeScheme): DshPalette {
  return scheme === 'dark' ? DSH_DARK : DSH_LIGHT;
}

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
    colorBgLayout: DSH_BG_BASE,
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
      activeShadow: `0 0 0 2px ${DSH_LINK_FOCUS_GLOW}`,
      hoverBorderColor: 'rgba(0, 0, 0, 0.28)',
    },
    Select: {
      activeBorderColor: DSH_LINK,
      activeOutlineColor: DSH_LINK_FOCUS_GLOW,
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
    // ── 主色族保险层（fix-dashboard-dark-theme-ui-defects 2.1）：ProLayout 内部
    // ConfigProvider scope 用 settings.colorPrimary 浅种子重算主色派生族，页签
    // 选中态/墨条/复选框/进度条在深档取 muddy 值。组件级显式 token 不依赖派生
    // 链（scope 重算也直达）。浅档值=antd 缺省派生现值（itemColor=colorText、
    // hover=colorPrimaryHover、selected/inkBar=colorPrimary），逐字节不变；
    // Tabs 选中态取 DSH_TEXT 与 theme.ts Menu 块 itemSelectedColor 先例同口径。
    // 圆角 MUST NOT 挂 borderRadius 覆写（2026-11-03 用户裁决，全档纪律）。
    Tabs: {
      itemColor: DSH_TEXT,
      itemHoverColor: DSH_PRIMARY_HOVER,
      itemSelectedColor: DSH_TEXT,
      inkBarColor: DSH_PRIMARY,
    },
    Progress: {
      // antd 缺省 defaultColor=colorInfo=本表 DSH_LINK，显式同值（深档由
      // components.Progress.dark 块给 DSH_LINK_DARK，不再信任 scope 派生）。
      defaultColor: DSH_LINK,
    },
    Checkbox: {
      // antd Checkbox 无专属主色组件 token，勾选底/悬停直取别名 colorPrimary 族
      // ——组件级别名覆写（antd 官方形态）把主色族键显式压进该组件 scope。
      colorPrimary: DSH_PRIMARY,
      colorPrimaryHover: DSH_PRIMARY_HOVER,
    },
    Radio: {
      // 同 Checkbox：选中圆点/边框直取别名 colorPrimary 族，显式给值。
      colorPrimary: DSH_PRIMARY,
      colorPrimaryHover: DSH_PRIMARY_HOVER,
    },
  },
} as const;

// ════ 深色档 ThemeConfig（置于浅档之后：darkSeedBgToken 守卫以首个 `Select: {`
// → 首个 `Button: {` 切片钉住浅档 Select 块，深档置后保切片语义）════

// antd 类型仅 type-only 引用：构建期类型检查用，运行时 import 被完全擦除
// （本文件保持零运行时 antd 依赖，pageChrome.test.mjs node 直载依赖此约束）。
import type { ThemeConfig } from 'antd';

/**
 * 深色档 ThemeConfig（antd v6）：`theme.darkAlgorithm` + D2 显式 token 覆写。
 * 关键面（bg/text/border/主控件族）全部显式给值，不信任 darkAlgorithm 派生
 * （Risks 表第一条）；圆角 MUST NOT 挂 borderRadius 覆写（2026-11-03 用户裁决，
 * 浅档同款纪律）。algorithm 由 app.tsx 传 antd `theme.darkAlgorithm` 注入。
 */
export const dshAlignedThemeDark = {
  token: {
    colorPrimary: DSH_PRIMARY_DARK,
    colorPrimaryHover: DSH_PRIMARY_HOVER_DARK,
    colorPrimaryActive: DSH_PRIMARY_ACTIVE_DARK,
    colorLink: DSH_LINK_DARK,
    colorInfo: DSH_LINK_DARK,
    colorSuccess: DSH_SUCCESS_DARK,
    colorError: DSH_ERROR_DARK,
    colorWarning: DSH_WARNING_DARK,
    colorText: DSH_TEXT_DARK,
    colorTextSecondary: DSH_TEXT_SECONDARY_DARK,
    colorTextTertiary: DSH_TEXT_TERTIARY_DARK,
    colorTextQuaternary: DSH_TEXT_CAPTION_DARK,
    colorBgLayout: DSH_BG_BASE_DARK,
    // 深档三层底显式压档：容器（卡/表/输入）=bg-layer-1、浮层（下拉/弹窗/
    // tooltip）=bg-module-platform——不依赖 darkAlgorithm 缺省（#141414 系，
    // 与宿主深色板不一致）。
    colorBgContainer: DSH_BG_ELEVATED_DARK,
    colorBgElevated: DSH_BG_MODULE_DARK,
    colorBorder: DSH_BORDER_DARK,
    colorBorderSecondary: DSH_BORDER_SECONDARY_DARK,
    colorSplit: DSH_SPLIT_DARK,
    // 主色种子派生陷阱（浅档黑种子同款处方，darkSeedBgToken.test.mjs）：白
    // 主色种子下 colorPrimaryBg 族为近白 ramp，「选中底」引用即白底白字。别名
    // 键显式压深底；Select 组件级三键同步显式（浅档同款「必须显式」纪律）。
    controlItemBgActive: DSH_BG_MODULE_DARK,
    controlItemBgActiveHover: DSH_BG_MODULE_DARK,
    controlHeight: DSH_CONTROL_HEIGHT,
    controlHeightSM: DSH_CONTROL_HEIGHT_SM,
    fontFamily: DSH_FONT_FAMILY,
  },
  components: {
    Input: {
      activeBorderColor: DSH_LINK_DARK,
      activeShadow: `0 0 0 2px ${DSH_LINK_FOCUS_GLOW_DARK}`,
      hoverBorderColor: 'rgba(255, 255, 255, 0.28)',
    },
    Select: {
      activeBorderColor: DSH_LINK_DARK,
      activeOutlineColor: DSH_LINK_FOCUS_GLOW_DARK,
      hoverBorderColor: 'rgba(255, 255, 255, 0.28)',
      optionActiveBg: DSH_BG_MODULE_DARK,
      optionSelectedBg: DSH_BG_MODULE_DARK,
      optionSelectedColor: DSH_TEXT_DARK,
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
      // 黑主色种子陷阱深档形态（design.md D2）：白主色下主按钮族缺省白底白
      // 字（colorTextLightSolid=白），必须显式给白底黑字档——墨档取页面基底
      // 反相（DSH_BG_BASE_DARK #151517），MUST NOT 用 DSH_TEXT_DARK（近白）。
      primaryColor: DSH_BG_BASE_DARK,
      primaryHoverColor: DSH_BG_BASE_DARK,
      primaryActiveColor: DSH_BG_BASE_DARK,
    },
    Table: {
      headerBg: DSH_BG_SOFT_DARK,
      headerColor: DSH_TEXT_SECONDARY_DARK,
      headerSplitColor: 'transparent',
      rowHoverBg: DSH_BG_MODULE_DARK,
    },
    Menu: {
      itemHeight: 36,
      itemSelectedBg: DSH_MENU_SELECTED_BG_DARK,
      itemSelectedColor: DSH_TEXT_DARK,
      itemHoverBg: 'rgba(255, 255, 255, 0.03)',
      // itemActiveBg 必须显式给值（antd 缺省走主色派生族，白种子下近白）。
      itemActiveBg: 'rgba(255, 255, 255, 0.06)',
    },
    // ── 主色族保险层深档（fix-dashboard-dark-theme-ui-defects 2.1，D2 值）：
    // ProLayout 内部 scope 以 settings.colorPrimary 浅种子重算主色派生族——
    // 深档下选中页签/墨条/复选框/进度条取 muddy 值（#101115/#6b94dc 系）。
    // 显式键不依赖派生链，scope 重算也直达（浅档同款「必须显式」纪律）。
    Tabs: {
      // 选中页签文字/墨条=近白主色（D2：黑主色→白主色反转），选中态在深底
      // 恢复可见（request.md 截图1/2 的「页签近隐」主缺陷面）。
      itemColor: DSH_TEXT_DARK,
      itemHoverColor: DSH_PRIMARY_HOVER_DARK,
      itemSelectedColor: DSH_TEXT_DARK,
      inkBarColor: DSH_PRIMARY_DARK,
    },
    Progress: {
      // 进度条取深档链接色（request.md 截图2「蓝色非深档链接色」收口）。
      defaultColor: DSH_LINK_DARK,
    },
    Checkbox: {
      // 勾选底白主色 + 悬停白主色 hover 档（别名覆写，浅档块同构）。
      colorPrimary: DSH_PRIMARY_DARK,
      colorPrimaryHover: DSH_PRIMARY_HOVER_DARK,
      // 勾选符号硬编码 colorWhite（antd checkbox/style：border: solid
      // token.colorWhite）——白主色种子下白底白勾不可见（浅档黑种子同款陷阱的
      // 深档反转形态，Button primaryColor 块同款处方：墨档取页面基底反相，
      // MUST NOT 用 DSH_TEXT_DARK 近白）。
      colorWhite: DSH_BG_BASE_DARK,
    },
    Radio: {
      // 选中圆点/边框白主色（同 Checkbox 构形）。antd radio 圆点
      // radioColor=colorWhite、实底 radioBgColor=colorPrimary——同款白底白点
      // 陷阱，colorWhite 反墨档。
      colorPrimary: DSH_PRIMARY_DARK,
      colorPrimaryHover: DSH_PRIMARY_HOVER_DARK,
      colorWhite: DSH_BG_BASE_DARK,
      // 实底按钮形态选中字（buttonSolidCheckedColor=colorTextLightSolid）同反墨。
      colorTextLightSolid: DSH_BG_BASE_DARK,
    },
  },
} as const;

/**
 * 按档取宿主对齐 ThemeConfig：浅档返回既有 `dshAlignedTheme`（行为与现状
 * 逐字节一致），深档返回 darkAlgorithm 档（algorithm 由调用方注入 antd
 * theme.darkAlgorithm）。app.tsx ConfigProvider 消费（dashboard-dark-theme 1.4）。
 */
export function dshThemeConfig(scheme: ThemeScheme, darkAlgorithm: ThemeConfig['algorithm']): ThemeConfig {
  return scheme === 'dark'
    ? { ...dshAlignedThemeDark, algorithm: darkAlgorithm }
    : dshAlignedTheme;
}

/**
 * 深色档 ProLayout 布局 token：soft 染色族深档（chrome 染色通道=DSH_BG_SOFT_DARK，
 * 玻璃双档只换 rgb 通道 alpha 档位不变——layout-chrome-tinting 深档同规）；
 * pageContainer 留白与浅档一致（几何不随主题变）。
 */
export const dshLayoutTokenDark = {
  // 主色族布局 token 通道（fix-dashboard-dark-theme-ui-defects 1.1 D1 兜底）：
  // ProConfigProvider 把 ProLayout token prop 经 getLayoutDesignToken 并入
  // finalToken 覆盖（override），top-level colorPrimary/colorLink 以 D2 深档
  // 显式值进入 pro 侧 token 计算——与 app.tsx runtime settings 覆写通道（
  // colorPrimary=DSH_PRIMARY_DARK）双保险，两通道验收口径一致（深档三个
  // scope 计算变量达标）。浅档 dshLayoutToken 不挂此键（浅档逐字节不变）。
  colorPrimary: DSH_PRIMARY_DARK,
  colorLink: DSH_LINK_DARK,
  header: {
    colorBgHeader: DSH_HEADER_GLASS_DARK,
    colorBgScrollHeader: DSH_HEADER_GLASS_SCROLL_DARK,
  },
  sider: {
    colorMenuBackground: DSH_BG_SOFT_DARK,
    // 选中项药丸底（2026-11-25 用户验收 1「选中高亮太亮看不清文字」）：ProLayout
    // 内层 ConfigProvider scope 以白主色种子重算派生族，itemSelectedBg 缺省
    // colorPrimaryBg → 深档下浅灰 #d7d8d8 药丸 + 白字不可读。显式给白 6% 药丸
    // （同 DSH_MENU_SELECTED_BG_DARK 值），与 global.less 深档 CSS 兜底层同构
    // 双保险（浅档 dshLayoutToken 不挂此键，逐字节不变）。
    colorBgMenuItemSelected: DSH_MENU_SELECTED_BG_DARK,
  },
  pageContainer: {
    paddingInlinePageContainerContent: 15,
    paddingBlockPageContainerContent: 0,
  },
} as const;

/**
 * 按档取布局 token（app.tsx `token: dshLayoutTokenFor(scheme)` 消费；浅档返回
 * 既有 `dshLayoutToken`，pageChrome.test.mjs 的 15px 断言消费浅档成立不变）。
 */
export function dshLayoutTokenFor(scheme: ThemeScheme) {
  return scheme === 'dark' ? dshLayoutTokenDark : dshLayoutToken;
}
