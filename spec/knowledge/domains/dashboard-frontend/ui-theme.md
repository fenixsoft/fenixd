<!-- knowledge: capability=ui-theme rev=2 sources=spec/archive/2026-09-02-add-dashboard-theme-switch,spec/changes/add-dashboard-dark-theme -->

# 界面主题（浅/深双档）

Dashboard 的浅/深双主题能力：三档偏好状态机、首帧防闪烁、嵌入宿主跟随与全站深色呈现。色值实现单源为 `core/dashboard/static/src/theme.ts`（浅/深双 token 族 + 按档取值助手）。

## 现行规则

- **三档偏好**：`system / light / dark`，持久化浏览器 localStorage 键 `fenix.theme`（值域即三档字符串）；缺省（无键/非法值）= `system` 跟随 `prefers-color-scheme` 并监听其变化实时切换（监听器随组件生命周期对称清理）。配置页「界面风格」页签三档单选即时生效，不参与 `PUT /api/config` 保存路径（v1 的「黑色风格缺省」行为已随 v1 面板退役）。
- **首帧防闪烁**：`config/config.ts` `headScripts` 注入内联脚本（Umi 4 headScripts 先于样式表执行），读 localStorage 偏好 + `embed=1` theme 参数 + prefers-color-scheme → 首帧前写 `data-fenix-theme`；脚本逻辑与 `src/utils/themePreference.ts` 状态机同构并注释互指，两处 MUST 同批改（themePreference.test.mjs 提取内联脚本直载断言三输入组合）。
- **token 单源**：`theme.ts` 每个语义常量浅/深两档（浅档与 2026-11 深色改造前逐字节一致=零回退基线；深档逐项翻译自 dsh web 深色调色板 `body[data-ds-dark-theme]` 档 `--dsw-*`，alias 语义对位——映射表见 spec/changes/add-dashboard-dark-theme design.md D2）。antd 侧深色档 `theme.darkAlgorithm` + 显式 token 覆写（darkAlgorithm 派生不信任）；**主色种子陷阱**双向成立：浅档黑主色与深档白主色下 `colorPrimaryBg` 派生族均不可作选中底（darkSeedBgToken 守卫），深档主按钮族必须显式白底黑字档（墨色=页面基底反相，MUST NOT 用近白文字）。MUST NOT 挂 theme 级 borderRadius 覆写（2026-11-03 用户裁决）；无过渡动画（静态渲染红线）。
- **CSS 变量双档**：`global.less` 存量硬编码已收敛为 `--fenix-*` 主题变量（`:root` / `[data-fenix-theme='dark']` 双档，值源 theme.ts 档位镜像同步）；页面组件的 JS 侧常量消费统一引 var() 形态（切档零 React 参与即时生效）；React 组件按档取值走 `utils/themeHooks` 的 `useThemeScheme`/`useDshPalette`（SSR 快照第三参必给，react-dom/server 渲染测试依赖）。深档布局 chrome（顶栏玻璃/侧栏 soft 底）双通道：`dshLayoutTokenFor` 运行时按档 + global.less 深档 CSS 覆写层兜底（值同源镜像恒一致）。
- **嵌入跟随（iframe 侧契约）**：嵌入 dsh web（`embed=1`）时主题跟随宿主——初始经挂载 search 可选参数 `theme=dark|light` 注入（值域白名单，缺省/非法回退独立逻辑），运行期经 host→iframe postMessage `{kind:'fenix-dashboard:theme', theme}` 实时切换（`utils/themeChannel.ts` 三层校验：`event.source===window.parent` + kind 白名单 + 值域，不合法静默忽略）。宿主档生效时嵌入态不读写 localStorage（不污染独立偏好）；嵌入态配置页「界面风格」控件锁定显示「跟随 dsh web」。宿主侧监听与广播由 dsh-plugins 桥接插件（独立立项 `add-bridge-theme-channel`）实现，kind 字面量与本侧 `THEME_MESSAGE_KIND` 双仓镜像逐字节一致。
- **全站深色呈现**：六页 + 指挥中心 + 全局组件深档可读；antd filled Tag 对自定义 hex 恒算浅色底，深档下自绘同色 alpha 形态（StatusTag filled 分支按档分流）；`progressPhase` 进度底轨淡色为 spec/用户指定浅色语义，**有意不随主题派生**（非遗漏）。

## 溯源

- 2026-09-02 add-dashboard-theme-switch（spec/archive/2026-09-02-add-dashboard-theme-switch） — v1 黑白双主题（`data-theme` + CSS 变量 + 缺省深色），随 v1 面板退役
- 2026-11-24 add-dashboard-dark-theme（spec/changes/add-dashboard-dark-theme/） — 现产规则重写：三档偏好缺省跟随系统、theme.ts 浅/深双 token 族（D2 映射表）、首帧防闪烁 headScripts、嵌入跟随 iframe 侧契约（URL theme 参数 + postMessage + 控件锁定）、global.less `--fenix-*` 变量双档收敛
