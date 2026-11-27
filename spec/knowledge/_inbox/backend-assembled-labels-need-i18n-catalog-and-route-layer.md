# 后端组装下发的展示标签：必须进 core/i18n.py 目录且路由层翻译

## 背景

国际化 spec（add-framework-i18n-zh-en）完成后，dsh web 英文档下指挥中心的五个分区标题（需求线/设计线/交付线/质量线/运营线）仍显示中文；同一时期 SPEC 列表代码审查页签的过滤下拉显示 `projects.quality.status.open` 这样的裸键名而非译文。前者是后端下发展示字符串漏翻译，后者是前端目录键漏登记。

## 结论（当前事实）

1. **后端组装下发的展示字符串不会自动过 umi 目录**。分区标题源自 `core/dashboard/data/command_center.py` 的 `ZONE_*` 常量（zh 字面量），经 `aggregate_org`（`zones[].zone`）与 `aggregate_spec_runs`（`lanes[].zone`）下发，前端（OrgGrid.tsx）直接渲染。这类标签必须在 `core/i18n.py` CATALOG 登记（键形 `label.zone.*`，zh 值与常量逐字一致），并在路由层按 `Accept-Language`（`resolve_locale`）改写响应字段后再下发；映射表外的 zone 值原样保留，防花名册演进时漏翻成静默中文。
2. **umi `formatMessage` 对未登记 id 回退返回键名本身**，且 `intlText` shim 的 truthy 检查会放行该回退——UI 直接显示裸键（如 `projects.quality.status.open`）。前端抽键（label 存目录键字符串、渲染期 `intl.formatMessage({id})`）时，键必须同步登记进 `src/locales/zh-CN.ts`（zh 是回退底座；en-US 为覆盖层）。漏登记在编译期零报错，只有真机切换语言才暴露。
3. **全仓守卫已固化**：`core/dashboard/static/tests/intlIdsRegistered.test.mjs` 扫描 src/**/*.{ts,tsx}（排除 locales）三种形态——`formatMessage({id:'字面量'})`、`intlText('…')`、`label:'键形字面量'`——断言全部命中 zh 目录键集；另断言动态拼键 `` `prefix.${` `` 必须存在同前缀族目录键。ALLOWLIST 机制供确凿误报豁免（当前仅 scheduler.py 一项：文件名字面量）。
4. 排查手法：自写三正则扫描 × zh 目录键集差集，比逐页真机点选可靠；注意键段含连字符（`components.alert.signal.*`）会被简单 `[a-z.]+` 正则漏掉，正则字符类需含 `-`。

## 证据

- 修复 commit：fenixd `76fef633f`（core/i18n.py label.zone.* 六键 + command_center_routes 路由层翻译 + locales 7 键补登记 + 守卫测试 + tests/test_i18n.py 两用例）。
- API 实证：`GET /api/command-center/org` 带 `Accept-Language: en` → zones `['Demand','Design','Delivery','Quality','Ops']`；无头/zh → 中文五区。
- 真机实证（dsh web 英/中文档）：指挥中心分区标题、代码审查页签状态下拉（en `open (pending)`/`in_spec (fix in spec)`/`resolved (written off)`/`ignored`；zh `open（待处置）` 等）均按档显示。
- 裸键名 git 考古：7 键引入于 commit `02c038226`（add-framework-i18n-zh-en 的 3.2-3.6 抽取轮漏登记），证明「抽键不登记」是该类回归的直接成因。

## 消费提示

新增后端下发标签或前端抽键时：先落 zh-CN.ts（或 core/i18n.py），再接线；守卫测试会在 npm test 拦截漏登记，但**后端组装标签没有前端扫描面**（值是 zh 常量非键形），只能靠 code review 对照本页第 1 条纪律。
