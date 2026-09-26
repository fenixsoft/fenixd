# 验证报告：add-quality-gates-visibility

> ⚠️ 本报告由框架于 2026-09-22T07:51:02Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T07:51:02.818741+00:00

## 结论：✅ 通过（verified）

**状态：verified — 25/25 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 25/25 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 25 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 11.53M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| seed-clean-slate | cli 清场：幂等清理夹具项目 /root/scheduling-showcase 全部 8 个 spec 的质量门禁产物（.fenix/verify-progress/<spec>/quality-gates.json 与 code-review.json 子目录、impl-<spec>-* 种子 run 产物含 archive）——上一验证轮残留的产物会污染本轮基线断言，全部场景以此为前置。夹具项目与 8 个 spec 名出处 bin/fixture_scheduling_showcase.py:41（ROOT）与 BASELINE_STATE（c-sched-set/c-sched-clear/c-sched-done/c-frozen-a..e）。 | pass | 0/3 | - |
| pytest-quality-gates-progress | cli 单测面：运行后端读侧合成/落盘契约/守卫软对账全量用例 tests/test_quality_gates_progress.py（48 用例，覆盖解析容错、框架 3 项合成、ocr 车道三态与指纹、worktree 优先、prompt 注入契约段、result_gate 宽松对账）——交付物 core/dashboard/data/quality_gates.py 与 core/agent_runner/{prompt_builder,result_gate}.py 的判定逻辑回归。-v 输出行形已实测（含 [implementer]/[fast-track] 参数化后缀）。 | pass | 0/9 | - |
| node-quality-gates-frontend-tests | cli 单测面：运行前端六态渲染语义与阶段映射纯函数用例 core/dashboard/static/tests/qualityGates.test.mjs（node --test 28 用例：done 含 skipped、failed 归因、running/skipped/unknown 后缀、Card 渲染条件、未知 gate-id 容错、gates 阶段 phasePct/配色 #fa8c16/#fff7e6、impl/verify 零回归）——detail.tsx/list.tsx 渲染映射逻辑回归。ℹ pass/fail 输出形态已实测。 | pass | 0/5 | - |
| seed-testing-ocr-running | cli 种子（c-sched-clear）：STATE.md 该 spec 块改写为 testing、写入渐进形态 quality-gates.json（full-suite passed 附计数 5297/0、frontend-build skipped 附非空 reason，interaction-contract 未写=渐进中间态）与 ocr 车道产物 code-review.json status=running——覆盖落盘契约渐进更新形态（specs/quality-gates-progress/spec.md「完成一项检查即渐进落盘」）与车道在飞态。读侧合成出处 core/dashboard/data/quality_gates.py:310（parse_quality_gates）。 | pass | 0/6 | - |
| seed-done-all-resolved | cli 种子（c-sched-done，基线即 done 态）：写入全了结形态 quality-gates.json（full-suite passed、frontend-build skipped+reason、interaction-contract passed）与 ocr 车道产物 code-review.json status=completed 附 findings 2 条/dispositions 1 条——6 道门禁全部了结（done=passed+skipped=6）的完成态。车道 completed→passed（detail 附计数摘要）合成出处 core/dashboard/data/quality_gates.py:242-253。 | pass | 0/4 | - |
| seed-impl-gates-window | cli 种子（c-frozen-a）：STATE.md 改写 implementing（frozen False、error null）、写 tasks.md 全部勾选（2/2）、写入仅含 full-suite passed 的渐进 quality-gates.json——implementing∧任务全勾∧门禁可见∧未全了结=gates 阶段第一支触发样本（core/dashboard/data/summary.py:308-313），同时是 run 进行中读侧渐进数据的样本。 | pass | 0/4 | - |
| seed-impl-guard-failed | cli 种子（c-frozen-b）：STATE.md 保持 blocked 但 error 改写为交付物词表归因「交付物守卫打回：缺交付物声明对账项」，写入 quality-gates.json（full-suite passed、frontend-build skipped+reason）——blocked∧error 命中交付物关键词词表（交付物/deliverable/dispute/格式复检，core/dashboard/data/quality_gates.py:57）→ deliverable-guard 门 failed 的样本。 | pass | 0/3 | - |
| seed-impl-tasks-partial | cli 种子（c-frozen-c）：STATE.md 改写 implementing、写 tasks.md 半勾（1/2）、写入 quality-gates.json（full-suite passed）——任务未全勾不进入 gates 阶段的反例样本（specs/task-progress-phase-display/spec.md「任务未全勾不进入 gates 阶段」），门禁进展只在详情页可见。 | pass | 0/3 | - |
| seed-impl-artifact-gate-failed | cli 种子（c-frozen-d）：STATE.md 改写 implementing、tasks.md 全勾、写入 quality-gates.json（full-suite passed、frontend-build skipped+reason），并伪造最新 impl run 产物 .fenix/runs/impl-c-frozen-d-<ts>-a1.jsonl（末行 gate-blocked 终态事件附归因）——run 终态=gate-blocked → result-artifact-gate 门 failed（detail 含截断归因）样本（core/dashboard/data/runs.py:140 gate-blocked 映射、quality_gates.py:_result_artifact_gate_status）。 | pass | 0/3 | - |
| seed-impl-no-gates-file | cli 种子（c-frozen-e）：STATE.md 改写 implementing、tasks.md 全勾、确保 quality-gates.json 不存在（rm 后不写）——门禁数据完全不可见（exists=false）不进 gates 阶段 + 详情页 implementing 态空态「暂无质量门禁记录」样本。 | pass | 0/3 | - |
| api-detail-failopen-unknown | api 契约：GET /api/specs/c-sched-set（ready 基线、quality-gates.json 从未存在）→ quality_gates.exists=false、run 内 3 项 unknown、框架 2 项 unknown、code-review pending、done=0/total=6、无 error 字段——历史 spec 无数据 fail-open（core/dashboard/routes/spec_routes.py:33 _api_spec_detail → spec_detail.quality_gates）。端点为被测交付端点，打真实实例禁止 mock。 | pass | 0/11 | - |
| web-detail-ready-no-card | 详情页 drafted/ready 且无门禁文件不渲染「质量门禁」Card：navigate /projects/scheduling-showcase/c-sched-set（ready 基线）→ data-testid=quality-gates-card 不存在，任务清单与验证进度 Card 照常渲染（core/dashboard/static/src/pages/projects/detail.tsx:1750 shouldRenderGatesCard 分支、qualityGates.ts shouldRenderGatesCard；路由 core/dashboard/static/config/routes.ts:22）。出处 detail.tsx:1750-1751。 | pass | 0/4 | - |
| api-specs-list-gates-phases | api 契约：GET /api/specs（列表 8 行，created 相同稳定序=STATE.md 序）→ 行级 progress_phase 窗口两支与回退：c-sched-clear(testing+lane running)="gates" 第二支且 gates_current=「ocr 代码审查与处置：进行中」、c-frozen-a(implementing 全勾 未了结)="gates" 第一支 gates_done=1、c-frozen-d 同第一支 gates_done=2、c-frozen-c(任务未全勾)="impl"、c-frozen-e(exists=false)="impl"、c-sched-done(done)="impl" 零回归、c-sched-set(ready)="impl"（core/dashboard/data/summary.py:303-314 判定单点；core/dashboard/routes/spec_routes.py:21 _api_specs）。 | pass | 0/19 | - |
| api-detail-testing-window | api 契约：GET /api/specs/c-sched-clear（testing+ocr 车道 running）→ quality_gates.done=4/6（passed+skipped 计入、running 不计）、full-suite passed（detail 含「通过 5297，失败 0」计数）、frontend-build skipped、code-review running（detail=「ocr 并行审查进行中」）、interaction-contract pending、框架 2 项 passed（testing∈implemented 及之后集合）——六道门逐项状态合成（core/dashboard/data/quality_gates.py:310 parse_quality_gates）。 | pass | 0/15 | - |
| api-detail-done-window | api 契约：GET /api/specs/c-sched-done（done 态全了结）→ quality_gates.done=6/total=6、code-review passed（detail 含「发现 2 条」「处置 1 条」计数摘要）、frontend-build skipped、其余 passed——ocr 车道 completed→passed 合成与 skipped 计入 done（core/dashboard/data/quality_gates.py:242-253、:356 done 口径）。 | pass | 0/10 | - |
| api-detail-failed-gates | api 契约（两连请求）：GET /api/specs/c-frozen-d → result-artifact-gate failed（detail 含 gate-blocked 归因原文）、done=2（failed 不计入）；GET /api/specs/c-frozen-b → deliverable-guard failed（detail 含「交付物守卫打回」归因）、gates_current 含「交付物守卫与格式复检：未通过」——两类守卫失败合成的读侧证据（core/dashboard/data/quality_gates.py:_result_artifact_gate_status/_deliverable_guard_status/_gates_current）。 | pass | 0/9 | - |
| web-detail-testing-midstate | 详情页门禁进行中中间态渲染：navigate c-sched-clear 详情 → 质量门禁 Card 可见、6 道 quality-gate-item、进度条「4 / 6」、code-review 行「（进行中）」后缀、frontend-build 行「（不适用）」后缀、full-suite 行辅助文案「通过 5297，失败 0」、「当前：ocr 代码审查与处置：进行中」、pending 项灰色——Card 内 Checkbox disabled 纯展示（detail.tsx:1751-1791、qualityGates.ts gateSuffix/gateDetailText）。 | pass | 0/9 | - |
| web-detail-done-full | 详情页全过门禁完成态渲染：navigate c-sched-done 详情 → Card 可见、6 项全勾（element_count=6）、「6 / 6」满格、code-review 行辅助文案「审查完成：发现 2 条、处置 1 条」、frontend-build 行「（不适用）」与 passed 删除线样式区分、列表顺序=契约固化顺序（quality-gates-progress spec「全过门禁的完成态渲染」；GATE_ORDER 顺序 quality_gates.py:37）。 | pass | 0/8 | - |
| web-detail-impl-inflight | 详情页 run 进行中渐进数据渲染：navigate c-frozen-a 详情 → 「全量回归测试」勾选+辅助计数、未写入的 frontend-build/interaction-contract 行 pending 灰色、框架 2 项「实现 run 在飞，收尾门禁未了结」pending、进度「1 / 6」——渐进落盘的读侧可见性（quality-gates-progress spec「run 进行中读 worktree 渐进数据」的详情页呈现；无 worktree 时读主树兜底 quality_gates.py:75-88）。 | pass | 0/7 | - |
| web-detail-artifact-gate-failed | 详情页打回循环 failed 渲染（产物硬门）：navigate c-frozen-d 详情 → 「结果文件产物硬门」行红色未勾选、辅助文案显示 gate-blocked 归因原文、「当前：结果文件产物硬门：未通过（…）」、进度「2 / 6」（failed 不计入 done）——用户可直接读出卡在哪道门（quality-gates-progress spec「打回循环中的 failed 渲染」；qualityGates.ts gateTextColor #cf1322、detail.tsx gateDetailText）。 | pass | 0/6 | - |
| web-detail-deliverable-guard-failed | 详情页打回循环 failed 渲染（交付物守卫）：navigate c-frozen-b 详情 → 「交付物守卫与格式复检」行红色、辅助文案=STATE error 归因、「当前：交付物守卫与格式复检：未通过（…）」——blocked 归因命中词表的 failed 合成呈现（quality_gates.py:266 _deliverable_guard_status；DELIVERABLE_BLOCKED_KEYWORDS:57）。 | pass | 0/5 | - |
| web-detail-empty-no-file | 详情页空态兜底：navigate c-frozen-e（implementing 但 quality-gates.json 不可见）详情 → 「质量门禁」Card 照常渲染（非 drafted/ready）且显示「暂无质量门禁记录」空态文案——exists=false 的空态与验证进度「暂无验证进度」同风格（detail.tsx:1786 空态分支；quality-gates-progress spec「未实现阶段不渲染 Card」的反面：其余状态恒渲染）。 | pass | 0/4 | - |
| web-list-testing-gates-orange | 列表页 gates 阶段第二支（testing+ocr 车道 running）橙条渲染：navigate 项目列表 → c-sched-clear 行任务进度格 data-testid=task-progress-cell 文案「4/6」、gates_current 辅助文案「ocr 代码审查与处置：进行中」、行内无 run 层存活线索（run-activity-active 不渲染）——gates 阶段 run 线索不出现（list.tsx:1076-1086 gates 计数分支、:1104-1109 gates_current 辅助、:1062-1064 runActive 仅 impl 分支）。 | pass | 0/6 | - |
| web-list-impl-gates-window | 列表页 gates 阶段第一支（implementing 收尾自查）橙条渲染：navigate 项目列表 → c-frozen-a 行任务进度格文案「1/6」（门禁完成度而非任务完成度 2/2）、无「已汇报」run 层线索——implementing∧全勾∧未了结时主条从零走门禁完成度（summary.py:308-313 第一支；list.tsx:1076 gates 分支数据源 gates_done/gates_total）。 | pass | 0/5 | - |
| web-list-gates-sort-and-impl-regression | 列表排序跟随显示值 + impl 阶段零回归：navigate 项目列表 → 点击「任务进度」列头（升序）→ c-frozen-a（1/6≈17%）行排在 c-frozen-d（2/6≈33%）之前（兄弟选择器断序）、列头 aria-sort=ascending（排序键已切门禁完成度，list.tsx sorter 与渲染共用 phasePct）；同时 c-sched-done 行（done 态 impl 阶段）任务进度格照常渲染（新增 gates 分支不触碰既有 impl 分支渲染路径）。 | pass | 0/6 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

