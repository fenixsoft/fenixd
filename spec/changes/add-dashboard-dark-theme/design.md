## Context

dashboard 前端（`core/dashboard/static/`，antd Pro v3）当前纯浅色：`src/theme.ts` 把 dsh web 浅色 token（`dsh-client-ui-theme` 注入的 `--dsw-*`）单向翻译为 antd ThemeConfig（`dshAlignedTheme`，`src/app.tsx:50` rootContainer 挂 ConfigProvider）与 `dshLayoutToken`。嵌入 dsh web（`embed=1`）后宿主切深色时浅色页面割裂。

dsh web 主题机制（已提取核实）：偏好三档 `light/dark/system`（默认 `system` 跟 `prefers-color-scheme`），持久化宿主 user-settings namespace `ui-theme`；深色档选择器 `body[data-ds-dark-theme]`，浅色档 `body{...}`，各 201 个 `--dsw-*` 变量（真相源：`@deepseek-ai/dsh-client-ui-theme@0.2.2-rc.1` 包 `lib/client.js` 的 `design_platform_css_default`，当前 theme.ts 手译自 0.2.0-rc.2）；插件消费契约 `ctx.theme.getTheme()` 快照 + `ctx.on("theme/change")` 事件。

设计约束以 `DESIGN.md` 为准：配色单源红线（一般域实现单源 theme.ts）、静态渲染红线（禁动画/transition，主题切换即时重渲染）、字号阶纪律、Bento 12px、配置页灰底准例（10px/#d7d7d7）、圆角纪律（MUST NOT 挂 theme 级 borderRadius 覆写，2026-11-03 用户裁决）。用户已确认：嵌入跟随 dsh web、独立访问默认「跟随系统」、嵌入态控件锁定显示、跳过原型（界面以本设计映射表 + DESIGN.md 为真相源）、full 模式。

## Goals / Non-Goals

**Goals:**

- theme.ts 扩展为浅/深双 token 族单源：浅色值与现状逐字节一致（零视觉回退风险）；深色值逐项翻译自 dsh web 深色调色板，视觉与宿主统一。
- 主题状态机：偏好 `system/light/dark`（缺省 `system`），localStorage 持久化，首帧防闪烁。
- 嵌入跟随：初始经 URL `theme` 参数注入，运行期经 host→iframe postMessage 实时切换；嵌入态宿主优先、控件锁定。
- 独立访问：配置页「界面风格」控件三档即时生效。
- 六页 + 指挥中心 + 全局组件深色回归通过。

**Non-Goals:**

- 不改 v1 老面板遗留行为语义（`ui-theme` 知识页描述的「默认深色」不复辟，缺省=跟随系统）。
- 不做主题过渡动画（静态渲染红线）。
- 不在本仓实现桥接侧宿主监听（dsh-plugins 项目独立立项 `add-bridge-theme-channel`；本 SPEC 只钉 iframe 侧契约与行为）。
- 不新增依赖包（antd `theme.darkAlgorithm` 内置）。

## Decisions

### D1 双 token 族单源（theme.ts 扩展，非新建并行文件）

`theme.ts` 内每个 DSH_* 语义常量改为浅/深两档（结构化 `light/dark` 记录），导出 `dshAlignedTheme(mode)` / `dshLayoutToken(mode)` 或等价形态；浅档值与现状逐字节一致。备选否决：运行时直读宿主 `--dsw-*` CSS 变量——独立访问无宿主变量、且运行时双来源违背配色单源红线；CSS filter 反色——破坏品牌色与截图证据。`app.tsx` ConfigProvider 按当前 effective scheme 传入对应 ThemeConfig。

### D2 深色值翻译表（alias 语义对位，勿按 static 名硬抄）

dsh 深色 `--dsw-*` 关键值 → dashboard 深档 DSH_*（static-* 阶在浅/深块内各自重定义，以 alias 语义逐项对位）：

| dashboard token（深档值） | dsh 深色来源（alias → 值） | 浅档对照（现状） |
|---|---|---|
| DSH_BG_BASE `#151517`（页面最外层基底：body/colorBgLayout 档） | dsh 深色档页面基底（本 SPEC dashboard-dark-theme 深色 Scenario 同值 #151517；实现期以 dsh-client-ui-theme 0.2.2-rc.1 包深色档逐项提取核准） | colorBgLayout `#ffffff`（theme.ts 现状） |
| DSH_BG_ELEVATED `#232324` | bg-layer-1 → bluish-875 #232324 | #ffffff |
| DSH_BG_MODULE `#353638` | bg-module-platform → bluish-800 #353638 | #f5f6f7 |
| DSH_BG_SOFT `#2c2c2e` | specific-input-major / bg-layer-2 → bluish-850 #2c2c2e | #f9fafb |
| DSH_BG_FLOATING_HOVER `#3a3b3d`（经 bg-layer-2/3 间派生，交互面抬升） | interactive-bg-hover #ffffff14 叠 layer | #f1f3f5 |
| DSH_BG_SOFT_GLASS `rgba(44,44,46,0.6)`、DSH_HEADER_GLASS `rgba(44,44,46,0.4)`（scroll 0.8） | 通道=深 DSH_BG_SOFT（layout-chrome-tinting 守卫） | rgba(249,250,251,…) |
| DSH_TEXT `#f9fafb` | label-primary → bluish-50 #f9fafb | #0f1115 |
| DSH_TEXT_SECONDARY `#cfd3d6` | label-secondary → bluish-300 #cfd3d6 | #61666b |
| TERTIARY `#adb2b8` | label-tertiary → bluish-400 #adb2b8 | #81858c |
| CAPTION `#81858c` | label-caption → bluish-600 #81858c | #adb2b8 |
| DSH_BORDER `rgba(255,255,255,0.16)`（L3 0.12 / SECONDARY 0.10 同构反相） | border-l1→#ffffff0f、l3→#ffffff29 等 alpha 系 | rgba(0,0,0,…) |
| DSH_SPLIT `rgba(255,255,255,0.08)`、OV_HAIRLINE `#2e2f31`（bg 上发丝线） | border 系 / layer 对齐 | rgba(0,0,0,0.08) / #eef2f7 |
| DSH_PRIMARY `#f9fafb`（黑主色→白主色）、HOVER `#ebeef2`、ACTIVE `#43454a` | brand-primary→bluish-50、button-primary-hover→bluish-100、button-elevated-fill→bluish-750 | #0f1115/#43454a/#2c2c2e |
| DSH_LINK `#7aaaff`（GLOW 12% alpha 派生不变） | link → deepseek-400 #7aaaff | #4176e6 |
| DSH_SUCCESS `#22c55e`（不变）、DSH_ERROR `#f25a5a`、DSH_WARNING `#f59e0b`（不变） | success green-500 / error red-400 / warn amber-500 | #22c55e/#ec1313/#f59e0b |
| DSH_INTERACTIVE_HOVER `rgba(255,255,255,0.08)`、ACTIVE `rgba(122,170,255,0.16)` | interactive-bg-hover #ffffff14 / active #ffffff24 + link 种子 | rgba(38,49,72,.06)/rgba(99,136,211,.1) |
| DSH_MENU_SELECTED_BG `rgba(255,255,255,0.06)` | menu 交互系白 alpha | rgba(0,0,0,0.04) |
| SPEC_LIST_MOBILE_BG `#2c2c2e`、SPEC_LIST 深底 | bg-layer-2 | #ffffff |
| OV_TEXT_TERTIARY `#8b8f94`（bg-module 上三级字） | label 三级在 layer-3 上的可读档 | #64748b |

antd 深色档：`theme.darkAlgorithm` + 上述 token 覆写。黑主色种子陷阱（知识页 command-center-console-ui 已登记）：darkAlgorithm 下主色派生族会产出黑底黑字，主按钮族必须显式给白底黑字档（token colorPrimaryText/colorBgContainer 等或 components 级覆写）；Input/Select optionActiveBg/optionSelectedBg、Table headerBg/headerColor/rowHoverBg、Menu itemSelectedBg/itemHoverBg/itemActiveBg 深档显式给值（沿用浅档「必须显式」纪律）。圆角：MUST NOT 挂 borderRadius 覆写。配置页灰底准例深档：卡底 `#2c2c2e`、边框加深 `#545557`（neutral-600，同「发丝线不可辨即失效」逻辑）。

### D3 主题状态机（`src/utils/themePreference.ts` 新模块 + 首帧防闪烁）

- 偏好档 `system|light|dark`，localStorage 键 `fenix.theme`（沿用 v1 键名；写入值域即三档字符串）。缺省（无键/非法值）=`system`。
- effective scheme 解析：`system` → `matchMedia('(prefers-color-scheme: dark)')`；嵌入态不读 localStorage（宿主优先，见 D4）。
- 应用方式：`document.documentElement` 挂 `data-fenix-theme="dark|light"` + React 根 ConfigProvider 切 ThemeConfig；`system` 档监听 matchMedia change。
- 首帧防闪烁：`config/config.ts` `headScripts` 注入内联脚本（实测 @umijs/max ^4.7.3，Umi 4 系；无 index.html 模板文件，headScripts 为官方注入口，产物先于 umi 样式表执行）：读 localStorage + `embed=1` URL 参数 + prefers-color-scheme → 首帧前写 `data-fenix-theme`。脚本逻辑与 themePreference 模块保持同构（注释互指）。

### D4 嵌入跟随通道（三层契约，iframe 侧）

- 初始：挂载 search 新增可选 `theme=dark|light`（桥接解析宿主快照后传具体值；省略=按独立逻辑）。`src/utils/embedMount.ts` 扩展第三参数：惰性缓存与 `_setEmbedSearchParamsForTest` 模式复用；值域白名单 `dark|light`，其余回退「未注入」。
- 实时：host→iframe postMessage，消息形状 `{kind:'fenix-dashboard:theme', theme:'dark'|'light'}`（kind 沿用既有 iframe 集成消息 `fenix-dashboard:*` 命名空间——同仓 embedBridge.ts `HOST_NEW_SESSION_KIND = 'fenix-dashboard:new-session'` 先例——并按其「双仓镜像值」纪律：桥接侧常量字面量与本值逐字节一致，client/index.ts:443 同款风格）。iframe 侧校验：`event.source === window.parent` + `kind` 白名单 + `theme` 值域；不合法静默忽略。
- 优先级：`embed=1` 时（URL 参数或消息）> localStorage 独立偏好；嵌入态配置页控件锁定。
- 备选否决：iframe 同源直读宿主 `body[data-ds-dark-theme]` + MutationObserver——耦合宿主内部 DOM 约定，宿主升级可能静默失效（用户已裁决双仓显式契约）。

### D5 设置控件与嵌入锁定

配置页新增「界面风格」分组：三档 Radio（跟随系统/浅色/深色，默认选中=当前偏好），变更即时生效+持久化，无需确认按钮。嵌入态（`isEmbedMode()`）渲染锁定态：disabled + 文案「跟随 dsh web」。命名纪律：页面整体叫「配置」（settings-page 能力页避让条款），控件名「界面风格」。DESIGN.md 字号阶/圆角纪律照常适用。

### D6 global.less 收敛（唯一允许的存量硬编码清理窗）

`global.less` 797 行内约 30 处硬编码浅色 hex/rgba（#eef2f7、#ffffff、#0f1115、#f6f6f6/#efefef、#d7d7d7、#4176e6、#f1f3f5 等）收敛为主题 CSS 变量：变量名与 theme.ts 语义常量一一对应，双档值经 `:root` / `[data-fenix-theme="dark"]` 定义；变量值来源单一（theme.ts 档位），global.less 不新增散落硬编码（配色单源红线）。存量色值逐项对档：V2_TILE_SHADOW 阴影系深档换黑 alpha；灰底准例 #d7d7d7/#f6f6f6 按 D2 表取深档；hairline/焦点环按映射表。毛玻璃守卫同步：深档 SOFT_GLASS/HEADER_GLASS 通道必须等于深档 DSH_BG_SOFT 且透明度<1。

### D7 回归面与验收

六页（overview/projects/settings/help/activities/command-center）+ PageTitleBar embed 毛玻璃带、StatusTag TONE_HEX 深档（6 tone 逐项）、DshIconButton、markdown-shared 代码块（深档 markdown-code-block #1b1b1c）、表格/Menu 经 darkAlgorithm + components 覆写。验收以浅色零变化（现状截图对齐）+ 深色逐页核查（截图证据入 `.history/`）执行。

## Risks / Trade-offs

- [antd darkAlgorithm 派生色与宿主深色板不一致] → 关键面（bg/text/border/主控件族）全部显式 token 覆写（D2），六页逐页截图核查兜底。
- [global.less 漏改导致深色下白块残留] → D6 逐项清单化：改前先 grep 产出硬编码色值全量清单，逐条归类（变量化/深档覆写/确属迁移件豁免族），验收核查清单对账。
- [首帧闪烁] → headScripts 内联脚本先于样式表执行（Umi 注入顺序保证），防闪烁脚本与模块逻辑同构并互指；Scenario 覆盖「localStorage 深 + 首帧即深」。
- [postMessage 伪造] → source===window.parent + kind 白名单 + 值域校验三层；不合法静默忽略不报错。
- [嵌入态与独立态状态互扰] → 嵌入态完全不读/不写 localStorage（宿主优先且不污染独立偏好）；切换 embed↔standalone 各自独立解析。
- [matchMedia 监听泄漏] → React 生命周期挂载/卸载对称清理（useEffect return disposer）。
- [知识页 stale 误导后续会话] → 本 SPEC 交付含 `spec/knowledge/domains/dashboard-frontend/ui-theme.md` 回填（v1 规则标注退役 + 现产双主题规则重写）。

## Migration Plan

纯前端静态产物重建（`core/dashboard/static` build → dist 为构建产物，交付声明 reference）。灰度天然成立：浅色档值逐字节不变，未切换主题的用户视觉零变化。回滚=还原 theme.ts/app.tsx/embedMount.ts/themePreference.ts 改动（单 commit 面，无数据迁移、无 API 变更）。

## Open Questions

无阻塞待决。桥接侧宿主监听实现时序不阻塞本 SPEC：嵌入跟随 Scenario 以「收到合法初始参数/postMessage 即生效」定义 iframe 侧行为，桥接侧在 dsh-plugins 项目独立立项（建议名 `add-bridge-theme-channel`）。
