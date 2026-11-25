<!-- knowledge: capability=locale-i18n rev=1 sources=spec/changes/add-framework-i18n-zh-en -->

# 界面语言（中英双语 i18n）

Dashboard 的中英双语能力：三档语言偏好状态机、首帧语言防闪烁、umi locale 机制、en 目录 spread 回退契约与三层消息面（前端目录 / 后端消息目录 / CLI）。结构镜像 ui-theme 页（同款三档偏好范式）。

## 规则

- **三档偏好**：`system / zh-CN / en-US`，持久化浏览器 localStorage 键 `fenix.locale`（值域即三档字符串）；缺省（无键/非法值）= `system`，跟随浏览器语言并经归一映射落受支持档（zh 系→zh-CN、en 系→en-US、其余→zh-CN；逐语言取 navigator.languages 第一个命中前缀）。配置页「界面语言」页签三档单选即时生效（不刷新页面），不参与 `PUT /api/config` 保存路径。浏览器语言运行期热变化不实时跟随（跟随档在解析时刻取值——与主题 matchMedia 监听不同，有意简化）。**嵌入态不锁定**：embed 态语言不跟随宿主 dsh web（与主题不同，不扩 embed 契约、零 dsh-plugins 改动，嵌入下行为与 standalone 一致）。
- **首帧语言防闪烁**：`config/config.ts` `headScripts` 注入内联脚本（先于 umi locale 插件初始化执行），读 `fenix.locale` 显式档 → 写 umi 内建 `umi_locale` 键；`system` 档先清 `umi_locale`（清键走浏览器判定）再按 navigator **归一落键**。归一根因：umi baseNavigator 只对 navigator.language 原样匹配（en-GB/ja 等值域外 locale 不在目录列表，getIntl 对未知 locale warning 后回退 default zh-CN——英文浏览器会错落中文），必须先归一成受支持档再落键。脚本与 `src/utils/localePreference.ts` 状态机同构并注释互指，两处 MUST 同批改（localePreference.test.mjs 提取内联脚本直载断言三输入组合）。
- **umi locale 机制**：`config.ts` 开启 `locale: { default: 'zh-CN', baseNavigator: true, antd: true }`；文案目录 Umi 约定路径 `src/locales/{zh-CN,en-US}.ts`。生效值应用 = umi `setLocale(target, false)`（内部写 umi_locale + 经内层 provider 的 LANG_CHANGE_EVENT 更新 context 值）。**运行时 API 约束**：`formatMessage` 静态导出被 umi 标注 deprecated（切语言不自动刷新）——组件内用 `useIntl()`（hook 订阅 context）；**非组件上下文用 `getIntl().formatMessage({id})` 渲染期求值；rootContainer（app.tsx ThemeRoot）位处 i18nProvider 外层（renderer 合成序 innerProvider→…→rootContainer 最外），该层 MUST NOT 调 useIntl（无 IntlProvider 祖先必抛错且无错误边界时整树卸载=冷启动白屏，2026-11-25 实证已修）——ThemeRoot 的 antd locale/dayjs 翻档经 localePreference 的 `LOCALE_APPLIED_EVENT` window 事件订阅**（applyLocale 派发；首启在 initLocalePreference 后直接同步一次，事件监听挂载晚于 boot 期应用）。菜单名（menuDataRender）/页题（pageTitleRender）/侧栏徽标文案渲染期 `getIntl()` 求值；routes.ts 的 name 是构建期 Node 快照（不可 import umi 运行时 API），从 zh 目录单源取中文作后备，运行时 title 由 pageTitleRender 接管。
- **en 目录 spread 回退契约**（design D3）：`en-US.ts` 导出 `{ ...zhCN, ...enOverrides }`——en 缺键运行时自动回落中文，永不裸键名；`enOverrides` 键集 MUST ⊆ zh 键集（守卫测试静态断言防拼写漂移）。键命名 `<域>.<页/组件>.<语义键>`；新增键 MUST 先落 zh-CN.ts（回退源）再补 enOverrides。**zh 目录是唯一回退底座**：zh 用户零感知迁移（zh 文案与现状逐字一致）。抽取推进方式：基建先行、逐页推进、抽查守卫拦截回潮（noHardcodedZh.test.mjs 对代表文件断言 JSX 字面量无中文，注释豁免）——不做全仓静态穷举。
- **三层消息面单源边界**：① 前端目录（本页）= 界面静态文案与前端 kind→标签映射（时间轴处置链事件标签、AGENT_LABEL、blockedPhaseMeta 等前端自有静态文案）；② 后端消息目录 `core/i18n.py`（CATALOG / t / resolve_locale）= Dashboard API 展示型字符串（error 字段、后端组装下发的展示标签/描述）——按请求 `Accept-Language` 解析（q 值降序前缀白名单 zh/en，非法回退 zh），响应结构/HTTP 状态零变化；内部运行日志、调试日志、落盘产物不改造（操作员面保持中文）；改造面盘点清单在 `core/i18n_surfaces.md`；③ CLI 人读提示（bin/fenix_cli.py）与后端共用 `core/i18n.py` 单源（MUST NOT 各自维护第二份字典），locale 解析链 `--lang` > `FENIX_LANG` 环境变量 > 配置 `general.locale` > 缺省 zh（白名单外回退 zh），退出码/行为语义/机器可读输出零变化。前端请求层统一附带 `Accept-Language`（生效档映射 zh-CN→zh / en-US→en，`currentAcceptLanguage` 零 umi import——dashboard.ts 被 node 直载测试引用）。
- **agent 提示词与文档非目标**：agents/*.md、skills/*/SKILL.md 不翻译（LLM 功能面，翻译可能改变 agent 行为）；docs/help/*.md 正文保持中文；SPEC 生成产物模板保持中文。

## 代码锚点

- 语言偏好状态机（三档解析/localStorage/浏览器归一映射/applier 注血）：core/dashboard/static/src/utils/localePreference.ts
- 首帧语言防闪烁内联脚本（headScripts，与状态机注释互指）：core/dashboard/static/config/config.ts（FIRST_FRAME_LOCALE_SCRIPT）
- umi locale 插件配置：core/dashboard/static/config/config.ts（locale 段）与 src/locales/{zh-CN,en-US}.ts（文案目录单源）
- bootstrap 接线（applier 注册→setLocale(target,false)、antd locale 动态挂、dayjs locale、档位经 LOCALE_APPLIED_EVENT window 事件订阅——rootContainer 在 i18nProvider 外层不可用 useIntl）：core/dashboard/static/src/app.tsx（ThemeRoot / layout）与 core/dashboard/static/src/utils/localePreference.ts（LOCALE_APPLIED_EVENT 派发单点）
- 配置页「界面语言」面板：core/dashboard/static/src/pages/settings/components/LocalePanel.tsx（页签登记 pageLabels.ts locale 键）
- 请求层 Accept-Language：core/dashboard/static/src/services/dashboard.ts（currentAcceptLanguage）
- 后端消息目录单源：core/i18n.py；改造面盘点：core/i18n_surfaces.md；_error 键展开：core/dashboard/routes/base.py
- CLI locale 解析链：bin/fenix_cli.py（_resolve_cli_locale）
- 配置键：core/config.py（general.locale，VALID_LOCALES 白名单校验）
- 守卫测试：core/dashboard/static/tests/localePreference.test.mjs、core/dashboard/static/tests/noHardcodedZh.test.mjs、tests/test_i18n.py

## 溯源

- 2026-11-25 add-framework-i18n-zh-en（spec/changes/add-framework-i18n-zh-en/） — 首版：前端 umi locale 基建与全站双语目录、后端消息目录单源与 Accept-Language 按请求解析、CLI 解析链四级、三档语言偏好状态机镜像主题范式
