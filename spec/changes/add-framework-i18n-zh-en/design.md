# 设计：框架国际化与中英文缺省支持

## Context

fenix 框架三层用户界面（Dashboard 前端 / 后端 API 展示消息 / CLI）全部只有中文文案：前端 139 个 ts/tsx 文件含中文（projects 27、settings 28、components 28、utils 18、command-center 7、overview/activities/help 等）、`fenixd.py` 约 3100 行含中文、`bin/fenix_cli.py` 93 行含中文。前端基于 `@umijs/max` 4.x（react-intl 内建、未启用）、antd 6、React 19；后端 API 错误经 `core/dashboard/routes/base.py` 的 `_error` 助手与各 route 自写 `_json` 输出；前端读路径集中在 `src/services/dashboard.ts` 的统一 fetch 封装（`reqHeaders` 构造点，约 287-295 行）。

既有先例：主题偏好已建立「三档状态机（system/light/dark，localStorage `fenix.theme`）+ 配置页面板 + 顶栏快捷入口 + 首帧防闪烁 headScripts + 守卫测试」的完整范式（知识页 `ui-theme`）；SPEC 命名体系已有「英文 id + 中文标题」双语数据基因。语言偏好设计直接镜像该范式。

## Goals / Non-Goals

**Goals**

1. 前端：全站静态文案中英双语，缺省跟随系统 locale，配置页手动切换持久化，antd 组件族文案联动，未覆盖键回退中文。
2. 后端：Dashboard API 展示型字符串（error 字段、展示标签）经消息目录输出，按请求 `Accept-Language` 解析语言，回退中文。
3. CLI：人读提示经同一消息目录输出，locale 解析链 `--lang` > `FENIX_LANG` > `general.locale` > `zh`。
4. 零新运行时依赖（前端 react-intl 由 umi 内建；后端纯 Python 字典）。

**Non-Goals**

- Agent 提示词（`agents/*.md`）、skills 文档（`skills/*/SKILL.md`）不翻译——LLM 功能面，翻译可能改变 agent 行为。
- `docs/help/*.md` 帮助文档正文、SPEC 生成产物模板（proposal/design/tasks）保持中文。
- 后端内部运行日志/调试日志不翻译（操作员面，非本期用户可见面）。
- embed 态语言不跟随宿主 dsh web（与主题不同，不扩 embed 契约、零 dsh-plugins 改动；嵌入下行为与 standalone 一致）。
- 浏览器系统语言运行期热变化不实时跟随（跟随档在解析时刻取值，与主题 matchMedia 监听不同，接受该简化）。

## Decisions

**D1 前端机制：Umi Max 内建 locale 插件，不引入独立 i18n 库。**
`config/config.ts` 开启 `locale: { default: 'zh-CN', baseNavigator: true, antd: true }`（antd: true 让 antd ConfigProvider locale 随 getLocale 自动联动；若实现时验证 antd 6 兼容问题，退化为 app.tsx 手动挂 antd locale 包）。文案目录用 Umi 约定路径 `src/locales/zh-CN.ts` / `en-US.ts`，消费侧 `useIntl` / `formatMessage`。备选 react-i18next 被否：与 umi 插件重复、多一份依赖与学习面。

**D2 语言偏好状态机：fenix 自有三档单源，镜像 themePreference。**
新增 `src/utils/localePreference.ts`：localStorage 键 `fenix.locale`，值域 `system | zh-CN | en-US`（缺省/非法回退 `system`）；生效语言 = 显式档 or 浏览器 locale 映射（zh 系→zh-CN、en 系→en-US、其余→zh-CN）。生效值经 umi `setLocale(target, false)` 应用（不刷新页面）。首帧防闪烁：`config/config.ts` headScripts 注入内联脚本（先于 umi locale 插件初始化执行），读 `fenix.locale` → 写/清 umi 内建 `umi_locale` 键，与状态机同构并注释互指（对齐 ui-theme 首帧防闪烁纪律）。手动切换即时生效 = 写偏好 + `setLocale(target, false)`；「跟随系统」= 清偏好 + 按当前 navigator 语言解析应用。配置页新增「界面语言」子项面板（三档 Radio，形态对齐 ThemePanel），挂 `pages/settings/index.tsx` BASE_MENU_ITEMS 与 pageLabels.ts。

**D3 en 目录以 zh 目录为缺省底座，运行时回退天然成立。**
`en-US.ts` 导出 `{ ...zhCN, ...enOverrides }`——未翻译键自动回落中文，杜绝「键名裸露」；守卫测试静态断言 overrides 键集 ⊆ zh 键集（防拼写漂移）。键命名 `<域>.<页/组件>.<语义键>`（如 `menu.overview`、`specTable.column.name`）。备选「每键强制双语齐全 + 缺键报错」被否：139 文件抽取量大，强制全齐会把交付与翻译质量耦合，spread 底座允许分批推进且永不出现裸键。

**D4 文案抽取推进方式：基建先行、逐页推进、守卫拦截回潮。**
基建（D1-D3）落地后按页抽取（projects → settings → overview → command-center → activities → 全局组件 → utils 常量），任务清单按页分组；每页完成 = JSX 字面量中文迁入目录 + `formatMessage` 接线。守卫测试新增两类：① 语言状态机守卫（三档解析/持久化/防闪烁脚本同构断言，形态对齐 themePreference.test.mjs）；② 抽查守卫——对已抽取页面的代表文件断言 JSX 字符串字面量无中文字符（注释中文豁免，抽查清单入 tasks），防新增硬编码回潮。全站无残留以逐页验收（playwright 巡检 en 档主要视图）兜底，不做全仓静态穷举（成本高误报多）。

**D5 后端消息目录：core 层单源模块 + Accept-Language 按请求解析。**
新增 `core/i18n.py`：`CATALOG`（键 → {zh, en}）、`t(key, locale='zh', **kw)`（en 缺键回退 zh、未知键原样返回键名）、`resolve_locale(accept_language: str|None) -> 'zh'|'en'`（逗号分隔 q 值前缀匹配白名单 zh/en，非法回退 zh）。routes 层展示型字符串改造点：① `base.py` `_error` 助手增加按请求头解析 locale 并支持消息键经目录展开（route 侧逐步把用户可见中文消息替换为键）；② 展示标签类（时间轴/处置链节点标签、Agent 展示标签、告警描述）在组装响应处经 `t()` 输出。前端 `services/dashboard.ts` 统一 fetch 封装的 `reqHeaders` 处附带 `Accept-Language`（getLocale 映射 zh-CN→zh / en-US→en），少量内联 fetch 点位同批补挂。范围判据：**前端直接渲染的文本**才进目录；判据落地的具体键清单由实现批在改造时盘点产出（附在分支内清单文件，评审对照）。

**D6 CLI：与后端共用 `core/i18n.py`，解析链四级。**
`core/config.py` 新增 `general.locale`（白名单 zh/en，缺省 zh，沿用既有作用域机制）；CLI 侧解析 `--lang` > `FENIX_LANG` > `general.locale` > `zh`；`bin/fenix_cli.py` 人读 print 文案改经 `t()`。退出码、行为语义、机器可读输出零变化。备选「CLI 独立小字典」被否：双字典必然漂移（Requirement: 消息目录跨车道共用 直接钉死单源）。

**D7 双语言缺省交付口径。**
「默认实现中英文版本」= zh-CN 与 en-US 两套目录随代码交付、两语言均为一等公民（非 en 机器翻译兜底）；zh 目录内容与现状文案保持一致（zh 用户零感知迁移），en 为对照翻译。交付判据不含「第三语言可插拔」——目录结构天然可扩展但本期不做语言包加载机制。

## Risks / Trade-offs

- [抽取遗漏：139 文件（Context 口径）全量抽取必有漏网] → D3 spread 底座保证漏网键显示中文而非裸键；D4 抽查守卫 + 逐页 playwright 巡检兜底；漏网项在验证批补齐。
- [umi locale 插件与 antd 6 兼容性未知] → 任务内先验证 antd:true 联动；不兼容走 D1 退化路径（手动 ConfigProvider locale），不阻塞交付。
- [en 翻译质量：技术术语（SPEC/晋升/处置链）译法不统一] → 目录内按域注释术语对照表（SPEC=present tense id 不译、晋升=promote、处置链=disposition chain），验证批按表复核。
- [后端 `_error` 消息改造涉及面广，可能触碰 200+error 形态既有守卫] → 只改文案来源不改响应结构；既有测试（如 test_api_alerts_unknown_project）全量回归，发现钉住具体文案字面量的测试同批改断言。
- [settings 页新增子项触碰「四处标签同步面」纪律（词汇对表）] → 新增子项命名「界面语言」，不触「设置」避让面；桥接插件 FIXED_ENTRIES 不涉及（无新路由/菜单项，仅设置页内子项）。
- [性能：目录体积与首帧] → 双目录静态打包，umi 按当前语言只加载对应 locale 块；无运行时字典拉取。

## Migration Plan

纯增量交付：zh 档渲染结果与现状一致（zh 用户零感知）；en 为新增能力。回滚 = 回退前端 commit（umi locale 关闭后 react-intl 调用点需同批回退，按整批 revert 设计，不做半回滚）；后端 `core/i18n.py` 未被目录改造的路径行为不变，回滚安全。

## Open Questions

（无——机制选型、缺省行为、范围边界均已与用户确认：范围=前端+后端展示消息+CLI；缺省=跟随系统+手动切换持久化；full 模式立即执行。）
