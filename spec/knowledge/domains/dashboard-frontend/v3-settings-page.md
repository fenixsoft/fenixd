<!-- knowledge: capability=v3-settings-page rev=3 sources=spec/archive/2026-09-08-add-v3-settings-page,spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md,spec/knowledge/_inbox/done/settings-menu-renamed-config-1105.md -->

# v3 设置页

v3 的统一设置入口：左侧子项菜单 + 右侧面板，复用 v1 配置后端，覆盖 Provider、模型分配、并行度、审批、预算与主题。

## 现行规则

- 用户可见命名统一为「配置」，避让 dsh web 官方「设置」（Settings）菜单——词汇对表：「配置」= fenix 本品、「设置」= dsh 官方。标签同步面共四处，须同批改齐（改一漏三即出现菜单/页题不一致）：fenixd `src/app.tsx` menuDataRender 侧栏菜单 `name`、`config/routes.ts` `/settings` 条目 `name`（document.title 链路）、`src/pages/settings/index.tsx` PageTitleBar `title`（统一标题栏页题单点声明）、dsh-plugins `fenix-dsh-dashboard-bridge/src/client/index.ts` FIXED_ENTRIES `fenix-settings` 条目 `label`（srcContract 断言同步改）。
- 稳定标识不随命名变化：路由 `/settings`、桥深链 `#/settings`、条目 id `fenix-settings` 均保持原名，更名只动 label/name，既有深链与书签零影响；`.umi/appData.json` 中的旧命名快照为构建临时产物，随 build 再生，非源码残留。
- 文档措辞现状：`docs/help/` 仍以「设置页」指称本页（09-config.md 面板映射表、08-dashboard.md 锚点 `#设置页settings`），与 UI 命名暂不一致；触及帮助文档的改动顺带统一——锚点含中文段，改锚点须同步内外链。
- `/settings` 路由采用 account/settings 风格布局：左侧竖向子项菜单（LLM Provider / Agent 模型分配 / 并行度设置 / 审批模式 / Token 预算 / 界面风格），右侧为当前子项面板；默认选中「LLM Provider」。页面纵向滚动为文档级（滚动条跨标题区域），左菜单列 sticky 钉住不随页面滚走——滚动形态与钉位常数细则由 dashboard-frontend 域 `document-scroll-unify` 单源承载。
- 配置经 `GET /api/config?project=<name>` 读取（复用 v1 后端，零后端改动）；支持用户级（无项目参数，写 `~/.fenix/config.yaml`）与项目级（写 `.fenix/config.yaml`）作用域切换，默认项目级；无配置文件时展示提示且表单为默认值；受管键在响应 `sources` 中标记 `user` 时，面板展示「继承自用户级」提示。
- LLM Provider 子项管理 `llm.providers` 列表：Provider 卡片（名称、baseurl、apikey、默认模型）支持追加空白卡片、编辑、删除，保存时整体写回数组。
- Agent 模型分配子项按 Agent 角色（KNOWN_AGENT_TYPES 全集）逐个分配：Provider 下拉（取自 `llm.providers`）+ 模型名（留空使用该 Provider 默认模型），写回 `agents.models`（`{provider, model}`）；作用域内无 Provider 时展示「请先在 LLM Provider 子项添加 Provider」引导。
- 并行度设置子项提供三个正整数：`agents.max_concurrent`（默认 2）、`agents.max_turns`、`agents.run_timeout_seconds`（秒），附严格优先级并行语义与「约 30 秒内热加载生效」说明。
- 审批模式子项为 `gates.approve_mode` 单选：manual（SPEC 完成后停留 done，等待人工推送）/ auto（自动推送）。
- Token 预算子项提供三个数值：`agents.token_budget_millions`（百万，0=关闭，默认 50）、`agents.daily_run_limit`（0=不限）、`agents.impl_run_budget`（1-10）。
- 界面风格子项提供亮色/暗色切换：选择后立即全站生效并写入浏览器 localStorage（键 `fenix.theme`）；不参与 `PUT /api/config` 保存路径。
- 各子项统一保存：保存前基础校验（数值范围等）；成功后提示并静默刷新配置数据；失败时展示可读错误（后端 `error` 字段优先），不重置用户已填写内容。

## 溯源

- 2026-09-08 add-v3-settings-page（spec/archive/2026-09-08-add-v3-settings-page） — 建立 v3 设置页六子项布局、作用域读写与继承标注、各子项配置键契约及统一保存 / 错误反馈
- 2026-11-05 settings-help-document-scroll-unify（spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md） — 布局规则随迁：页面文档级滚动、左菜单 sticky 钉住（滚动形态细则归 document-scroll-unify 单源）
- 2026-11-05 settings-menu-renamed-config-1105（spec/knowledge/_inbox/done/settings-menu-renamed-config-1105.md） — 全表面命名规则入库：统一「配置」避让 dsh 官方「设置」、四处标签同步面、路由/深链/条目 id 不改名、docs/help 措辞残余登记
