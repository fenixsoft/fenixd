<!-- knowledge: capability=locale-i18n rev=2 sources=spec/changes/add-framework-i18n-zh-en,spec/knowledge/_inbox/done/backend-assembled-labels-need-i18n-catalog-and-route-layer.md -->

# 界面语言（中英双语 i18n）

Dashboard 的中英双语能力：三档语言偏好状态机、首帧语言防闪烁、umi locale 机制、en 目录 spread 回退契约与三层消息面（前端目录 / 后端消息目录 / CLI），以及后端组装标签与 daemon 落盘回链文案的翻译收口纪律。结构镜像 ui-theme 页（同款三档偏好范式）。

## 规则

- **三档偏好**：`system / zh-CN / en-US`，持久化浏览器 localStorage 键 `fenix.locale`（值域即三档字符串）；缺省（无键/非法值）= `system`，跟随浏览器语言并经归一映射落受支持档（zh 系→zh-CN、en 系→en-US、其余→zh-CN；逐语言取 navigator.languages 第一个命中前缀）。配置页「界面语言」页签三档单选即时生效（不刷新页面），不参与 `PUT /api/config` 保存路径。浏览器语言运行期热变化不实时跟随（跟随档在解析时刻取值——与主题 matchMedia 监听不同，有意简化）。**嵌入态不锁定**：embed 态语言不跟随宿主 dsh web（与主题不同，不扩 embed 契约、零 dsh-plugins 改动，嵌入下行为与 standalone 一致）。
- **首帧语言防闪烁**：`config/config.ts` `headScripts` 注入内联脚本（先于 umi locale 插件初始化执行），读 `fenix.locale` 显式档 → 写 umi 内建 `umi_locale` 键；`system` 档先清 `umi_locale`（清键走浏览器判定）再按 navigator **归一落键**。归一根因：umi baseNavigator 只对 navigator.language 原样匹配（en-GB/ja 等值域外 locale 不在目录列表，getIntl 对未知 locale warning 后回退 default zh-CN——英文浏览器会错落中文），必须先归一成受支持档再落键。脚本与 `src/utils/localePreference.ts` 状态机同构并注释互指，两处 MUST 同批改（localePreference.test.mjs 提取内联脚本直载断言三输入组合）。
- **umi locale 机制**：`config.ts` 开启 `locale: { default: 'zh-CN', baseNavigator: true, antd: true }`；文案目录 Umi 约定路径 `src/locales/{zh-CN,en-US}.ts`。生效值应用 = umi `setLocale(target, false)`（内部写 umi_locale + 经内层 provider 的 LANG_CHANGE_EVENT 更新 context 值）。**运行时 API 约束**：`formatMessage` 静态导出被 umi 标注 deprecated（切语言不自动刷新）——组件内用 `useIntl()`（hook 订阅 context）；**非组件上下文用 `getIntl().formatMessage({id})` 渲染期求值；rootContainer（app.tsx ThemeRoot）位处 i18nProvider 外层（renderer 合成序 innerProvider→…→rootContainer 最外），该层 MUST NOT 调 useIntl（无 IntlProvider 祖先必抛错且无错误边界时整树卸载=冷启动白屏，2026-11-25 实证已修）——ThemeRoot 的 antd locale/dayjs 翻档经 localePreference 的 `LOCALE_APPLIED_EVENT` window 事件订阅**（applyLocale 派发；首启在 initLocalePreference 后直接同步一次，事件监听挂载晚于 boot 期应用）。菜单名（menuDataRender）/页题（pageTitleRender）/侧栏徽标文案渲染期 `getIntl()` 求值；routes.ts 的 name 是构建期 Node 快照（不可 import umi 运行时 API），从 zh 目录单源取中文作后备，运行时 title 由 pageTitleRender 接管。
- **en 目录 spread 回退契约**（design D3）：`en-US.ts` 导出 `{ ...zhCN, ...enOverrides }`——en 缺键运行时自动回落中文，永不裸键名；`enOverrides` 键集 MUST ⊆ zh 键集（守卫测试静态断言防拼写漂移）。键命名 `<域>.<页/组件>.<语义键>`；新增键 MUST 先落 zh-CN.ts（回退源）再补 enOverrides。**zh 目录是唯一回退底座**：zh 用户零感知迁移（zh 文案与现状逐字一致）。抽取推进方式：基建先行、逐页推进、抽查守卫拦截回潮（noHardcodedZh.test.mjs 对代表文件断言 JSX 字面量无中文，注释豁免）——不做全仓静态穷举。
- **三层消息面单源边界**：① 前端目录（本页）= 界面静态文案与前端 kind→标签映射（时间轴处置链事件标签、AGENT_LABEL、blockedPhaseMeta 等前端自有静态文案）；② 后端消息目录 `core/i18n.py`（CATALOG / t / resolve_locale）= Dashboard API 展示型字符串（error 字段、后端组装下发的展示标签/描述）——按请求 `Accept-Language` 解析（q 值降序前缀白名单 zh/en，非法回退 zh），响应结构/HTTP 状态零变化；内部运行日志、调试日志、落盘产物不改造（操作员面保持中文）；改造面盘点清单在 `core/i18n_surfaces.md`；③ CLI 人读提示（bin/fenix_cli.py）与后端共用 `core/i18n.py` 单源（MUST NOT 各自维护第二份字典），locale 解析链 `--lang` > `FENIX_LANG` 环境变量 > 配置 `general.locale` > 缺省 zh（白名单外回退 zh），退出码/行为语义/机器可读输出零变化。前端请求层统一附带 `Accept-Language`（生效档映射 zh-CN→zh / en-US→en，`currentAcceptLanguage` 零 umi import——dashboard.ts 被 node 直载测试引用）。
- **后端组装标签必经后端目录 + 路由层翻译**：后端组装下发的展示字符串不会自动过 umi 目录——典型如指挥中心五分区标题，源自 `core/dashboard/data/command_center.py` 的 `ZONE_*` 常量（zh 字面量），经 `aggregate_org`（`zones[].zone`）与 `aggregate_spec_runs`（`lanes[].zone`）下发后前端直接渲染。这类标签 MUST 在 `core/i18n.py` CATALOG 登记（键形 `label.zone.*`，zh 值与常量逐字一致），并由下发路由按 `Accept-Language`（`resolve_locale`）改写响应字段后再下发；映射表外的 zone 值原样保留——花名册演进新增 zone 漏登记时宁可透出中文，不静默假翻。后端组装标签的值是 zh 常量而非键形字符串，**没有前端扫描面可依赖**，漏翻只能靠 code review 对照本条纪律拦截。
- **前端抽键必须同步登记 zh 目录**：umi `formatMessage` 对未登记 id 回退返回键名本身，且 `intlText` shim 的 truthy 检查会放行该回退——UI 直接显示裸键（如 `projects.quality.status.open`）。前端抽键（label 存目录键字符串、渲染期 `intl.formatMessage({id})`）时，键 MUST 同步登记进 `src/locales/zh-CN.ts`（zh 是回退底座；en-US 为覆盖层）。漏登记编译期零报错，只有真机切换语言才暴露。
- **目录键登记守卫**：`intlIdsRegistered.test.mjs` 扫描 `src/**/*.{ts,tsx}`（排除 locales）三种形态——`formatMessage({id:'字面量'})`、`intlText('…')`、`label:'键形字面量'`——断言命中键全部在 zh 目录键集内；动态拼键 `` `prefix.${` `` 形态要求存在同前缀族目录键；ALLOWLIST 机制供确凿误报豁免（现仅 scheduler.py 文件名字面量一项）。排查手法：自写三正则扫描 × zh 目录键集求差集，比逐页真机点选可靠；键段含连字符（如 `components.alert.signal.*`）会被 `[a-z.]+` 类正则漏掉，字符类 MUST 含 `-`。
- **daemon 落盘回链结果文案只在读侧收口**：回链结果文案（toast 面）由 daemon 主循环消费信号时以 zh 原文写进 `.fenix/*_request_result.json`——写侧天然无 locale 上下文，不做翻译；翻译收口在读侧三条 GET 路由（`/api/code-review/run-result`、`/api/code-review/fix-run-result`、`/api/regression/fix-result`），按 `Accept-Language` 以 payload `reason` 组键改写 `message` 字段，键族 `label.reviewResult.*` / `label.codeFixResult.*` / `label.regressionFixResult.*`。路由内即时组装的 message（autodraft 同步回包）有 handler 上下文，直接 `t(key, _i18n_locale(handler))`。改写 MUST 先查目录成员再 `t()`——`t()` 对未知键原样返回键名，直接改写会把假键名漏进 UI；缺键或 zh 档原样透传（宁 zh 不假翻）。组键契约陷阱：started 受理回执以 `reason=None` 落盘（测试断言依赖），组键须回退取 `status`（`reason or status or ''`）。
- **双源文案同步守卫**：回链文案 zh 值双源（fenixd.py 三张文案表 + CATALOG）必然漂移——`tests/test_i18n.py` 正则解析 fenixd.py 文案表源码，逐条断言登记且 zh 逐字相等。双源文案 MUST 配这类源码级同步测试，否则 daemon 侧改文案后 en 档翻旧文案、zh 档静默变化，两者皆不可见。
- **遗留裸 zh 错误文案面**：routes 内大量中文字面量多为 daemon 日志（非用户面）不改造，但 `_coded_error(409, "已有回归在进行中", …)` 这类裸 zh 错误文案会以 `e.message` 落到前端 toast；存量同类面按 `t(key, locale)` 模式分模块逐步收口。
- **agent 提示词与文档非目标**：agents/*.md、skills/*/SKILL.md 不翻译（LLM 功能面，翻译可能改变 agent 行为）；docs/help/*.md 正文保持中文；SPEC 生成产物模板保持中文。

## 代码锚点

- 语言偏好状态机（三档解析/localStorage/浏览器归一映射/applier 注血）：core/dashboard/static/src/utils/localePreference.ts
- 首帧语言防闪烁内联脚本（headScripts，与状态机注释互指）：core/dashboard/static/config/config.ts（FIRST_FRAME_LOCALE_SCRIPT）
- umi locale 插件配置：core/dashboard/static/config/config.ts（locale 段）与 core/dashboard/static/src/locales/zh-CN.ts、core/dashboard/static/src/locales/en-US.ts（文案目录单源）
- bootstrap 接线（applier 注册→setLocale(target,false)、antd locale 动态挂、dayjs locale、档位经 LOCALE_APPLIED_EVENT window 事件订阅——rootContainer 在 i18nProvider 外层不可用 useIntl）：core/dashboard/static/src/app.tsx（ThemeRoot / layout）与 core/dashboard/static/src/utils/localePreference.ts（LOCALE_APPLIED_EVENT 派发单点）
- 配置页「界面语言」面板：core/dashboard/static/src/pages/settings/components/LocalePanel.tsx（页签登记 pageLabels.ts locale 键）
- 请求层 Accept-Language：core/dashboard/static/src/services/dashboard.ts（currentAcceptLanguage）
- 后端消息目录单源：core/i18n.py；改造面盘点：core/i18n_surfaces.md；_error 键展开：core/dashboard/routes/base.py
- 后端组装标签源常量与聚合计下发：core/dashboard/data/command_center.py（ZONE_* 常量 / aggregate_org / aggregate_spec_runs）；路由层翻译：core/dashboard/routes/command_center_routes.py
- 回链结果读侧改写（_i18n_locale / CATALOG 成员检查 / reason or status 组键）：core/dashboard/routes/code_review_routes.py、core/dashboard/routes/regression_routes.py
- daemon 文案表（回链文案 zh 双源之一）：fenixd.py（CODE_REVIEW_RESULT_MESSAGES / CODE_FIX_RESULT_MESSAGES / REGRESSION_FIX_RESULT_MESSAGES）
- intlText shim（truthy 检查放行键名回退）：core/dashboard/static/src/utils/intlText.ts
- CLI locale 解析链：bin/fenix_cli.py（_resolve_cli_locale）
- 配置键：core/config.py（general.locale，VALID_LOCALES 白名单校验）
- 守卫测试：core/dashboard/static/tests/localePreference.test.mjs、core/dashboard/static/tests/noHardcodedZh.test.mjs、core/dashboard/static/tests/intlIdsRegistered.test.mjs、tests/test_i18n.py

## 溯源

- 2026-11-25 add-framework-i18n-zh-en（spec/changes/add-framework-i18n-zh-en/） — 首版：前端 umi locale 基建与全站双语目录、后端消息目录单源与 Accept-Language 按请求解析、CLI 解析链四级、三档语言偏好状态机镜像主题范式
- 2026-11-27 backend-assembled-labels-need-i18n-catalog-and-route-layer（spec/knowledge/_inbox/done/backend-assembled-labels-need-i18n-catalog-and-route-layer.md） — 折叠：后端组装标签（指挥中心 ZONE_*）目录登记+路由层翻译纪律、前端目录键漏登记裸键直显与登记守卫（intlIdsRegistered 三形态扫描）、daemon 落盘回链文案读侧收口（CATALOG 成员检查/reason or status 组键）、双源文案源码级同步守卫、遗留裸 zh 错误文案面
