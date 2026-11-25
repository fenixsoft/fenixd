<!-- knowledge: capability=settings-page rev=8
     sources=spec/archive/2026-09-08-add-v3-settings-page,spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md,spec/knowledge/_inbox/done/settings-menu-renamed-config-1105.md,spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md,spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md,spec/knowledge/_inbox/done/2026-11-16-spec-list-icon-buttons-and-settings-deeplink.md,spec/changes/add-dashboard-dark-theme,spec/changes/add-framework-i18n-zh-en -->

# 设置页

统一设置入口（/settings）：左侧子项菜单 + 右侧面板，复用既有配置后端，覆盖 Provider、模型分配、并行度、审批、预算、主题与界面语言。

## 现行规则

- 用户可见命名统一为「配置」，避让 dsh web 官方「设置」（Settings）菜单——词汇对表：「配置」= fenix 本品、「设置」= dsh 官方。标签同步面共四处，须同批改齐（改一漏三即出现菜单/页题不一致）：fenixd `src/app.tsx` menuDataRender 侧栏菜单 `name`、`config/routes.ts` `/settings` 条目 `name`（document.title 链路）、`src/pages/settings/index.tsx` PageTitleBar `title`（统一标题栏页题单点声明）、dsh-plugins `fenix-dsh-dashboard-bridge/src/client/index.ts` FIXED_ENTRIES `fenix-settings` 条目 `label`（srcContract 断言同步改）。
- 稳定标识不随命名变化：路由 `/settings`、桥深链 `#/settings`、条目 id `fenix-settings` 均保持原名，更名只动 label/name，既有深链与书签零影响；`.umi/appData.json` 中的旧命名快照为构建临时产物，随 build 再生，非源码残留。
- 文档措辞现状：`docs/help/` 仍以「设置页」指称本页（09-config.md 面板映射表、08-dashboard.md 锚点 `#设置页settings`），与 UI 命名暂不一致；触及帮助文档的改动顺带统一——锚点含中文段，改锚点须同步内外链。
- 页面全量卡片挂 Bento 边框三件套（软阴影 + 圆角 10px + 加深边框 #d7d7d7，global.less 单源规则作用于本页所有 `.ant-card.ant-card-bordered`；卡头随卡根圆角同形 10px 10px 0 0）。本页为浅灰卡底（#f6f6f6/#efefef 条款不变，边框规则只接管边框）——浅灰底上 #eef2f7 发丝线不可辨，边框不可见即失效，故不走白磁贴 12px 发丝边条款；灰底准例仅此一页（DESIGN.md 通用条款登记），MUST NOT 推广至白底磁贴页。覆写位置纪律：Bento 边框规则必须后置于同特异性的页级直角化规则（border-radius: 0）之后，守卫测试钉住先后顺序。
- `/settings` 路由采用 account/settings 风格布局：左侧竖向子项菜单（LLM Provider / Agent 模型分配 / Prompts / 并行度设置 / Token 预算 / 验证 / 代码质量 / 审批模式 / 杂项 / 系统 / 自进化 / 决策者车道 / 界面风格 / 界面语言，页签顺序与键以 `BASE_MENU_ITEMS` 单源为准，项目级作用域追加自省/项目/Hook 三页签），右侧为当前子项面板；默认选中「LLM Provider」。页面纵向滚动为文档级（滚动条跨标题区域），左菜单列 sticky 钉住不随页面滚走——滚动形态与钉位常数细则由 dashboard-frontend 域 `document-scroll-unify` 单源承载。
- 标题栏作用域控件移动端瘦身：顶栏 filters 槽位「作用域：」标签在移动端（<768px）不渲染，作用域 Select 宽度按视口分档——移动档 130（对齐 v2 配置页移动档同值）、桌面档 200；顶栏窄幅下标签+宽下拉会把标题行挤到换行，故移动端收窄。
- 配置经 `GET /api/config?project=<name>` 读取（复用 v1 后端，零后端改动）；支持用户级（无项目参数，写 `~/.fenix/config.yaml`）与项目级（写 `.fenix/config.yaml`）作用域切换，页面首屏默认用户级作用域；无配置文件时展示提示且表单为默认值；受管键在响应 `sources` 中标记 `user` 时，面板展示「继承自用户级」提示。
- 首屏作用域深链预选：URL 携带 `?project=<名>` 时首屏预选项目级作用域并选中该工程（`initialScopeFromUrl` 为该参数唯一读侧）；参数缺省/为空回落用户级，与无深链进入行为一致。hash 路由下 query 位于 `location.hash` 的 `?` 之后（读法同 activities 页 initialTab 先例）。仅首屏生效：`useState` 惰性初始化单次取值，scope/project 两 state 共用同一 `initialScope`，此后作用域由受控 Select 驱动（切档丢弃确认弹窗不变），URL 不回写、不参与后续状态流转。深链入口为 SPEC 列表页「配置」钮（接线见 spec-list-titlebar-buttons 页）。
- LLM Provider 子项管理 `llm.providers` 列表：Provider 卡片（名称、baseurl、apikey、默认模型）支持追加空白卡片、编辑、删除，保存时整体写回数组。
- Agent 模型分配子项按 Agent 角色（KNOWN_AGENT_TYPES 全集）逐个分配：Provider 下拉（取自 `llm.providers`）+ 模型名（留空使用该 Provider 默认模型），写回 `agents.models`（`{provider, model}`）；作用域内无 Provider 时展示「请先在 LLM Provider 子项添加 Provider」引导。
- 并行度设置子项提供三个正整数：`agents.max_concurrent`（默认 2）、`agents.max_turns`、`agents.run_timeout_seconds`（秒），附严格优先级并行语义与「约 30 秒内热加载生效」说明。
- 审批模式子项为 `gates.approve_mode` 单选：manual（SPEC 完成后停留 done，等待人工推送）/ auto（自动推送）。
- Token 预算子项提供三个数值：`agents.token_budget_millions`（百万，0=关闭，默认 50）、`agents.daily_run_limit`（0=不限）、`agents.impl_run_budget`（1-10）。
- 界面风格子项提供主题偏好三档单选（跟随系统/浅色/深色，缺省跟随系统）：选择后立即全站生效并写入浏览器 localStorage（键 `fenix.theme`，值域三档字符串）；不参与 `PUT /api/config` 保存路径。嵌入 dsh web（`embed=1`）时渲染锁定态：控件置灰 + 「跟随 dsh web」文案，主题由宿主控制（URL theme 参数/postMessage），嵌入态不读写 localStorage（dashboard-dark-theme；现产规则单源见 ui-theme 页）。
- 界面语言子项提供语言偏好三档单选（跟随系统/中文/English，缺省跟随系统并按浏览器 locale 归一映射落受支持档）：选择后即时全站生效（不刷新页面）并写入浏览器 localStorage（键 `fenix.locale`，值域三档字符串）；不参与 `PUT /api/config` 保存路径。嵌入态不锁定——语言不随宿主 dsh web（与界面风格不同，不扩 embed 契约），嵌入下行为与 standalone 一致；语言机制细则（umi locale、防闪烁、三层消息面）单源见 locale-i18n 页。
- 各子项统一保存：保存前基础校验（数值范围等）；成功后提示并静默刷新配置数据；失败时展示可读错误（后端 `error` 字段优先），不重置用户已填写内容。

## 代码锚点

- 主实现（左菜单 BASE_MENU_ITEMS 单源 + 右面板路由）：core/dashboard/static/src/pages/settings/index.tsx
- 「界面风格」子项控件与嵌入锁定态：core/dashboard/static/src/pages/settings/components/ThemePanel.tsx
- 「界面语言」子项控件：core/dashboard/static/src/pages/settings/components/LocalePanel.tsx

## 溯源

- 2026-09-08 add-v3-settings-page（spec/archive/2026-09-08-add-v3-settings-page） — 建立 v3 设置页六子项布局、作用域读写与继承标注、各子项配置键契约及统一保存 / 错误反馈
- 2026-11-05 settings-help-document-scroll-unify（spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md） — 布局规则随迁：页面文档级滚动、左菜单 sticky 钉住（滚动形态细则归 document-scroll-unify 单源）
- 2026-11-05 settings-menu-renamed-config-1105（spec/knowledge/_inbox/done/settings-menu-renamed-config-1105.md） — 全表面命名规则入库：统一「配置」避让 dsh 官方「设置」、四处标签同步面、路由/深链/条目 id 不改名、docs/help 措辞残余登记
- 2026-11-06 overview-ledger-bento-align-1106（spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md） — 新增全量卡片 Bento 边框三件套规则：圆角 10px + 加深边框 #d7d7d7（浅灰卡底发丝线不可辨的灰底准例，仅此一页）、卡头随形、覆写后置于直角化规则的位置纪律
- 2026-11-07 mobile-ui-fixes-1107（spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md） — 新增标题栏作用域控件移动端瘦身条款：「作用域：」标签移动端不渲染、Select 宽度移动档 130（对齐 v2 配置页移动档同值）桌面档 200，防顶栏窄幅标题行换行
- 2026-11-16 2026-11-16-spec-list-icon-buttons-and-settings-deeplink（spec/knowledge/_inbox/done/2026-11-16-spec-list-icon-buttons-and-settings-deeplink.md） — 新增首屏作用域深链预选规则（`?project=` 非空预选项目级并选中该工程、唯一读侧 initialScopeFromUrl、仅首屏生效 URL 不回写）；首屏默认作用域口径修正为用户级（原「默认项目级」表述退役）
- 2026-11-24 add-dashboard-dark-theme（spec/changes/add-dashboard-dark-theme/） — 新增「界面风格」子项规则（三档单选、localStorage `fenix.theme`、不参与 PUT /api/config、嵌入态锁定）；布局规则段的子项菜单全集随页签落地登记
- 2026-11-25 add-framework-i18n-zh-en（spec/changes/add-framework-i18n-zh-en/） — 新增「界面语言」子项规则（三档单选、localStorage `fenix.locale`、即时生效不刷新页面、不参与 PUT /api/config、嵌入态不随宿主）；子项菜单全集补登记界面语言；语言机制细则归 locale-i18n 页单源
