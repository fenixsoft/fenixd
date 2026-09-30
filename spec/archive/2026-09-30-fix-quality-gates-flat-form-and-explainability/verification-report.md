# 验证报告：fix-quality-gates-flat-form-and-explainability

> ⚠️ 本报告由框架于 2026-09-24T06:10:14Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-24T06:10:14.701191+00:00

## 结论：✅ 通过（verified）

**状态：verified — 24/24 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 24/24 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 24 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 13.23M |
| 本链增量 Token（输出） | 0.14M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| seed-gates-artifacts-clean | cli 清场（幂等）：清理本轮 3 个主用夹具 spec（c-sched-set/c-sched-clear/c-sched-done）与 2 个告警合成 spec（c-gates-demo-flat/c-gates-demo-multi）的 verify-progress 门禁产物、框架侧回归快照 last-run.json，并清掉上轮 c-gates-demo-* 的 quality-gates-form-drift 告警残留——夹具与 8 spec 基线出处 bin/fixture_scheduling_showcase.py:41-51（ROOT=/root/scheduling-showcase 与 BASELINE_STATE，verify.yaml prepare 每轮复位，此处防御性幂等兜底）。；并对 c-frozen-a 的 verify-progress 门禁产物做防御性幂等清理（2026-09-22 上轮种子残留实测会破坏 api-frozen-readonly-empty 的无文件空态前置，读侧对在场文件合法返回 exists=true）。 | pass | 0/5 | - |
| pytest-gates-regression | cli 单测面：运行后端门禁读侧合成/平铺容错六分支/兜底文案/宽松对账告警全量用例（tests/test_quality_gates_progress.py 的 TestFlatFormTolerance+TestFallbackAttributionDetail 与 tests/test_quality_gates_soft_alert.py 的 TestFourViolationClassesAlert+TestDedup+TestFailOpen+TestSoftBoundaryZeroRegression），断言关键用例 PASSED（-v 输出形态，无参数化后缀）与退出码 0。契约源 specs/quality-gates-form-tolerance 与 specs/quality-gates-explainability 与 specs/quality-gates-soft-gate-alerts 的单测层全分支。出处 tests/test_quality_gates_progress.py:203,295；tests/test_quality_gates_soft_alert.py:66,117,150,166。 | pass | 0/25 | - |
| node-gates-frontend-pure-fn | cli 前端纯函数面：node --test 运行 core/dashboard/static/tests/qualityGates.test.mjs（六态→渲染语义映射：gateChecked/gateTextColor/gateSuffix/gateDetailText/shouldRenderGatesCard），断言退出码 0 且 TAP 汇总 # fail 0——本 SPEC 前端零改动，此用例钉住「detail 透传链既有断言零变化」。出处 core/dashboard/static/tests/qualityGates.test.mjs；core/dashboard/static/src/pages/projects/qualityGates.ts:68。 | pass | 0/2 | - |
| cli-soft-alert-failopen | cli 进程内装配（一次性临时项目根，零夹具污染）：admin_alerts.json 存储位被同名目录占位使写入必败 → 宽松对账仍正常返回 None 不抛异常（告警写入 fail-open：仅记 WARNING 日志，run 收尾与对账主流程零影响）。specs/quality-gates-soft-gate-alerts「告警通道故障 fail-open」。出处 result_gate.py:790-816（整体 try/except fail-open）；临时根置于验证树 .history/（gitignore 排除）避免路径断言污染。 | pass | 0/3 | - |
| seed-flat-pure | cli 种子（c-sched-set 保持 ready 基线）：写顶层平铺形态 quality-gates.json（无 gates 包裹层：full-suite passed 附计数 12/0、frontend-build skipped 附 reason「无前端改动」、interaction-contract passed 附 reason，外加字符串型元数据键 updated_at）——specs/quality-gates-form-tolerance「纯平铺形态被采信」的输入样本。出处 bin/fixture_scheduling_showcase.py:41 ROOT；quality_gates.py:512 _adopt_flat_form。 | pass | 0/3 | - |
| cli-soft-alert-flat | cli 进程内装配（打夹具项目，AdminMonitor 对 fixture 项目抑制调用不入裁决流）：对平铺形态文件（c-gates-demo-flat）调用宽松对账 _check_quality_gates_soft → admin_alerts 新增一条记录：signal_type=quality-gates-form-drift、severity=info、handled=false、无 choices（不可裁决信号桶）、description 含 spec 名与「顶层缺 gates 对象」及文件相对路径；同时返回 None 且夹具 STATE.md 字节不变（软约束边界：无打回无失败终态）。specs/quality-gates-soft-gate-alerts「平铺形态违规产生人工可见告警」+「软约束边界零回归」。出处 core/agent_runner/result_gate.py:766,819-879；core/admin_store.py:64（.fenix/admin_alerts.json）。 | pass | 0/2 | - |
| cli-soft-alert-dedup-multiclass | cli 进程内装配（合成 spec c-gates-demo-multi 顺序触发四类违规）：bad-json → out-of-contract-gate-id → out-of-enum-status → 重复 bad-json——断言前三类各落一条告警（violation_class 机器可读类别各异，同 spec 异类别不互斥），第四步同类别重复触发命中去重不新增（append_if_absent 返回 None），最终恰 3 条。specs/quality-gates-soft-gate-alerts「未处理告警不重复刷屏」+ 四类违规覆盖（契约外 gate-id/status 枚举外/JSON 无法解析）。出处 result_gate.py:783-786,892-902；core/admin_store.py:252 append_if_absent。 | pass | 0/2 | - |
| api-frozen-readonly-empty | api 契约（只读验收，不动冻结 spec）：GET /api/specs/c-frozen-a?project=scheduling-showcase（blocked 冻结基线、无门禁文件）→ exists=false、full-suite unknown 空详情获兜底文案「门禁记录缺失或损坏」、deliverable-guard 为 pending「SPEC blocked（非交付物归因）」（blocked 归因未命中交付物词表，非空 detail 零覆盖）——缺文件空态下兜底文案照常合成、冻结 spec 零扰动。specs/quality-gates-explainability「unknown 空详情获得兜底文案」+「已有归因文案零覆盖」。出处 quality_gates.py:502-506；fixture BASELINE_STATE c-frozen-a blocked+用户指令冻结。 | pass | 0/10 | - |
| api-flat-adopted | api 契约：GET /api/specs/c-sched-set?project=scheduling-showcase → 平铺形态被采信——3 项 run 自查门按落盘值合成（full-suite passed 且 detail 透传「通过 12，失败 0」计数摘要、frontend-build skipped「无前端改动」、interaction-contract passed），done=3（2 passed+1 skipped）；code-review 车道产物不可见 → pending 空详情获兜底文案「该门未了结（run 在飞或自查结果未落盘）」；ready 态框架 2 项 unknown 空详情获「门禁记录缺失或损坏」——specs/quality-gates-form-tolerance「纯平铺形态被采信」+ specs/quality-gates-explainability「pending/unknown 空详情获得兜底文案」。端点为被测交付读侧的真实出口，打真实实例禁止 mock。出处 core/dashboard/routes/base.py:323；core/dashboard/data/summary.py:764。 | pass | 0/18 | - |
| api-alerts-visible-channel | api 契约：GET /api/alerts?project=scheduling-showcase（dashboard 告警面板「按项目查询」同源数据路径，显式查询不排除夹具）→ 响应含 quality-gates-form-drift 信号与 c-gates-demo-flat/c-gates-demo-multi 两个 spec 的告警（body 子串断言，ASCII 键名对中文转义形态免疫）——宽松对账形态违规脱离「只有 daemon 日志」盲区、人工可见性通道成立。specs/quality-gates-soft-gate-alerts「平铺形态违规产生人工可见告警」（可见性通道面）。出处 core/dashboard/routes/alert_routes.py:43 _api_alerts（?project 分支）；夹具被跨项目聚合排除（:75 fixture 跳过），故以按项目 API 作可见性验收。 | pass | 0/5 | - |
| seed-flat-badstatus | cli 种子（c-sched-set 改写）：平铺形态混入「status 枚举外」的 dict 值（full-suite: "status": "ok"）——specs/quality-gates-form-tolerance「平铺含枚举外 status 整体不采信」的输入样本（宁可 pending 不误读半个文件）。出处 quality_gates.py:538-539 枚举外即整体拒绝。 | pass | 0/2 | - |
| api-flat-badstatus-rejected | api 契约：平铺含枚举外 status → 整体不采信，file_gates 视为空——已落盘的 frontend-build passed 也不采信（合成 pending 而非 passed，证明非部分采信），各 run 门 pending 空详情获兜底文案、exists 仍 true（文件可见可读）。specs/quality-gates-form-tolerance「平铺含枚举外 status 整体不采信」+「空顶层 dict 不采信」同分支语义。出处 quality_gates.py:539；base.py:323。 | pass | 0/9 | - |
| seed-flat-empty-top | cli 种子（c-sched-set 改写）：文件为合法 JSON 但顶层是空 dict {}——候选门集为空的边界分支样本。specs/quality-gates-form-tolerance「空顶层 dict 不采信」。出处 quality_gates.py:534-541（候选集空 → 返回空 dict 不采信）。 | pass | 0/3 | - |
| api-flat-empty-top-rejected | api 契约：空顶层 dict → 不采信平铺，维持既有「文件可读但键未写 → pending」语义：exists=true、3 项 run 门 pending 且空详情获兜底文案「该门未了结（run 在飞或自查结果未落盘）」。specs/quality-gates-form-tolerance「空顶层 dict 不采信」。出处 quality_gates.py:539；base.py:323。 | pass | 0/9 | - |
| seed-corrupt-json | cli 种子（c-sched-set 改写）：写入非法 JSON（截断字节流「{not-json」）——「文件损坏」语义样本：损坏文件同样可见（exists=true）但不可解析。specs/quality-gates-form-tolerance「损坏文件语义不变」。出处 quality_gates.py:114-130 _read_json_candidate（解析失败 data=None exists=True）。 | pass | 0/3 | - |
| api-corrupt-unknown | api 契约：非法 JSON → 维持既有 (None, exists=true) → unknown「门禁记录缺失或损坏」语义，平铺判定不参与——3 项 run 门 unknown 且 detail 为兜底文案，区别于 pending 的归因（损坏 vs 未了结）。specs/quality-gates-form-tolerance「损坏文件语义不变」+ specs/quality-gates-explainability「unknown 空详情获得兜底文案」。出处 quality_gates.py:284-286；base.py:323。 | pass | 0/9 | - |
| seed-nested-priority | cli 种子（c-sched-set 改写）：合法嵌套形态 gates 键在场（frontend-build skipped 附 reason「嵌套值胜出」），顶层另放一个同名 gate 形态杂散键（frontend-build passed）——最强判别样本：若误走平铺采信，杂散的 passed 会被采信。specs/quality-gates-form-tolerance「嵌套形态优先零回归」。出处 quality_gates.py:577-581（gates 为 dict 时平铺判定不参与）。 | pass | 0/2 | - |
| api-nested-priority-zero-regression | api 契约：嵌套 gates 键在场时读侧行为与本变更前逐字节一致——items[1]（frontend-build）取嵌套值 skipped「嵌套值胜出」而非顶层杂散键的 passed，平铺判定不参与。specs/quality-gates-form-tolerance「嵌套形态优先零回归」。出处 quality_gates.py:579-581；base.py:323。done=1（嵌套 frontend-build skipped 被采信即计入 done，与 api-flat-adopted done=3 含 skipped 同口径）。 | pass | 0/6 | - |
| seed-impl-flat-mixed | cli 种子（c-sched-clear 置 implementing）：STATE.md 状态块改写为 implementing 并写平铺形态渐进门禁文件（frontend-build passed 附 reason「vite build 通过」、interaction-contract skipped 附 reason「纯后端改动」、full-suite 未写=渐进落盘中间态）——实现中态 + 平铺容错 + 兜底文案「只填空不覆盖」的混合样本。出处 bin/fixture_scheduling_showcase.py BASELINE_STATE 状态块形态；quality_gates.py:62 兜底文案。 | pass | 0/3 | - |
| api-impl-flat-mixed | api 契约：implementing 态 + 平铺采信的「只填空不覆盖」——full-suite 未写 pending 空详情获兜底文案、frontend-build passed detail「vite build 通过」透传、code-review pending 兜底文案、框架 2 项 implementing 归因「实现 run 在飞，收尾门禁未了结」非空原样保留（零覆盖实证）、done=2（1 passed+1 skipped）。specs/quality-gates-explainability「已有归因文案零覆盖」+「pending 空详情获得兜底文案」。出处 quality_gates.py:492,508,620-623；base.py:323。 | pass | 0/16 | - |
| web-gates-fallback-ui | web 详情页「无解释未勾选项消除」渲染：navigate c-sched-clear（implementing、平铺文件）→ 门禁 Card 可见、6 项齐全、pending 空详情项携带兜底文案「该门未了结（run 在飞或自查结果未落盘）」、implementing 归因「实现 run 在飞，收尾门禁未了结」原样可见（零覆盖）、skipped reason「纯后端改动」透传、进度条「2 / 6」——兜底文案由读侧填充经既有 gateDetailText 透传链渲染，前端零改动。specs/quality-gates-explainability「UI 无解释未勾选项消除」。出处 hash 路由 core/dashboard/static/config/config.ts:15 与 routes.ts:23（/projects/:name/:spec）；门禁 Card core/dashboard/static/src/pages/projects/detail.tsx:1830；透传 qualityGates.ts:68；进度条 ProgressBarTile.tsx:24。 | pass | 0/8 | - |
| seed-done-failed | cli 种子（c-sched-done 保持 done 终态基线，不动 STATE）：写合法嵌套形态门禁文件（frontend-build failed 附归因 reason「tsc 类型检查失败： 3 errors」）——终态豁免与 failed 归因原文保留的输入样本。出处 quality_gates.py:80-81 终态豁免；fixture BASELINE_STATE（c-sched-done status: done）。 | pass | 0/3 | - |
| api-done-preserve | api 契约：done 终态 → full-suite 走终态豁免 skipped「SPEC 已终态，全量回归跟踪移交主树」（有文案不在兜底范围，零覆盖）、frontend-build failed 归因原文透传、框架 2 项 passed 固定文案、done=3（skipped+2 passed）。specs/quality-gates-explainability「已有归因文案零覆盖」（failed 归因/终态豁免文案）。出处 quality_gates.py:415-416,486,500；base.py:323。 | pass | 0/14 | - |
| web-gates-done-preserve-ui | web 详情页完成态渲染：navigate c-sched-done（done 终态 + 嵌套 failed 门禁文件）→ 终态豁免文案「SPEC 已终态，全量回归跟踪移交主树」与 failed 归因原文「tsc 类型检查失败： 3 errors」同屏可见（归因多样性零覆盖）、框架守卫 passed 文案在场、进度「3 / 6」——UI 不出现无解释未勾选项。specs/quality-gates-explainability「UI 无解释未勾选项消除」+「已有归因文案零覆盖」。出处 detail.tsx:1830；qualityGates.ts:59-64（unknown 后缀）与 :68。 | pass | 0/7 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

