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

## 追轮（同课第二形态）：daemon 落盘回链结果文案（toast 类）

指挥中心分区之后，同类问题出现在 toast 提示面：en 档收到「已把回归问题转入修复台账并投递一批自动修复…」。这批文案与分区标题同根但有独立机制约束，收口 commit fenixd `1f1836727`：

1. **写侧天然无 locale 上下文**：文案由 daemon 主循环消费信号时写进 `.fenix/*_request_result.json`（CODE_REVIEW_RESULT_MESSAGES 9 条 / CODE_FIX_RESULT_MESSAGES 15 条 / REGRESSION_FIX_RESULT_MESSAGES 覆写 2 条），翻译只能收口在读侧 GET 路由（`/api/code-review/run-result`、`/fix-run-result`、`/api/regression/fix-result`），按 `Accept-Language` 以 payload 的 `reason` 组键改写 `message` 字段；键族 `label.reviewResult.* / label.codeFixResult.* / label.regressionFixResult.*`。
2. **改写必须查目录成员再动手**：`core/i18n.py t()` 对未知键原样返回键名，直接改写会把假键名漏进 UI——helper 先 `key in CATALOG` 再 `t()`；缺键/zh 档原样透传（宁 zh 不假翻）。
3. **历史契约有组键陷阱**：started 受理回执以 `reason=None` 落盘（测试断言依赖），组键时须回退取 `status`（即 `reason or status or ''`）。
4. **文案表↔目录同步守卫**：zh 值双源（fenixd.py 文案表 + CATALOG）必然漂移——tests/test_i18n.py 正则解析 fenixd.py 三张表源码，逐条断言登记且 zh 逐字相等。双源文案 MUST 配这种源码级同步测试，否则 daemon 改文案后 en 档翻旧文案、zh 档静默变化，两者皆不可见。
5. 同批收口：autodraft 同步回包 4 条 message（路由内即时组装，有 handler 上下文，直接 `t(key, _i18n_locale(self))`）。
6. 遗留同类面（未迁移，量大）：routes 全仓约 396 条中文字面量多为 daemon 日志（非用户面），但 `_coded_error(409, "已有回归在进行中", code)` 这类裸 zh 错误文案仍会以 `e.message` 落到前端 toast——后续迁移按 4.4 `t(key, locale)` 模式分模块收口。
