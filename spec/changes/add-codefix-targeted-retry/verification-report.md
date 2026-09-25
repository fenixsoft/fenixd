# 验证报告：add-codefix-targeted-retry

> ⚠️ 本报告由框架于 2026-09-25T07:19:36Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T07:19:36.290075+00:00

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.95M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| targeted-retry-suite-all-green | 定向重试轮新增单测套件全绿（24 例：junit→nodeid 映射 9 例、门面子集命令 7 例、门面透传 2 例、编排循环 6 例）——tasks 4.1-4.5 验证主入口。出处 tests/test_codefix_targeted_retry.py:1-610、spec/changes/add-codefix-targeted-retry/tasks.md 任务 4 | pass | 0/8 | - |
| targeted-retry-map-classname-primary | 失败明细 nodeid 映射以 junit classname 主导重构（1.1/D1）：模块级函数 tests.test_x+test_a → tests/test_x.py::test_a；类链 tests.test_x.TestFoo+test_bar → tests/test_x.py::TestFoo::test_bar；pytest junitxml 缺 file 属性属预期形态不判映射失败；失败摘要截取 200 字内。出处 core/code_fix.py:566-634 _map_junit_failures_to_nodeids、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:38 | pass | 0/2 | - |
| targeted-retry-map-failclosed-variants | nodeid 映射 fail-closed 变体（1.2/D1）：非 Python 模块形态 classname、缺 classname、file 属性与重构不一致、任一用例映射失败整体判失败、tests/test_x.py 与 tests/test_x/TestFoo.py 并存的歧义边界——均返回 ok=False，调用方据此回退全量重试。出处 core/code_fix.py:591-634（段校验/边界歧义/一致性校验）、tests/test_codefix_targeted_retry.py:238-297 | pass | 0/2 | - |
| targeted-retry-detail-write-structure | 回归失败用例明细结构化落盘（1.1）：文件名含该轮回归 run_id（fix-reg-failures-<run_id>.json，置于 .fenix/code-review/），结构含 items/source_run_id/created_at/fallback_full；映射失败形态 fallback_full=true 且 items 尽力保留为空。出处 core/code_fix.py:533-563 fix_reg_failures_relpath/write_fix_reg_failures、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:38 | pass | 0/2 | - |
| targeted-retry-subset-command-replace | 门面子集命令改写以「取代既有收集位置参数」语义实现（2.1/D2）：shell/argv 两态、多收集目标折叠为子集（防并集退化全量）、-q/--junit-xml/-k 及其值等非收集旗标逐字保留；非 pytest 形态、无收集目标、含 shell 操作符均返回 None（fail-closed 回退全量）。出处 core/agent_runner/maintenance_runs.py:1489-1549 _apply_pytest_subset、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:13 | pass | 0/2 | - |
| targeted-retry-subset-e2e-execution | 门面 run_regression 端到端子集回归（2.1）：临时 pytest 项目 3 例，传失败子集 1 例经门面真实执行——快照 total=1（只跑失败集）；命令无既有收集目标时忽略子集跑全量——快照 total=3（fail-closed 到现状语义）。出处 core/agent_runner/maintenance_runs.py:1552-1618 run_regression、core/regression.py:865-901 快照 total 统计 | pass | 0/2 | - |
| targeted-retry-first-pass-zero-rounds | 首轮全量回归 passed → 零定向轮（4.1/「首轮通过零定向轮」场景）：仅 1 次 run + 1 次回归、不传子集、正常合回核销，主路径与现状逐字一致。出处 tests/test_codefix_targeted_retry.py:431-448、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:61-64 | pass | 0/3 | - |
| targeted-retry-fail-subset-then-merge | 首轮失败 k 例 → 定向轮子集回归只执行 k 例、passed → 合回核销（4.2/「定向轮通过即过回归门」）：subset_calls=[None, k 例 nodeids]、注入累计明细含 nodeid+摘要+MUST NOT 硬指令、合回一次、条目 resolved、明细落盘文件名含该轮回归 run_id 且 fallback_full=false。出处 tests/test_codefix_targeted_retry.py:450-490、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:29-32,46-49 | pass | 0/3 | - |
| targeted-retry-fix-scope-test-kept | 修测试路径 fix_scope=test 标注经编排读取透传保留（4.3/「测试自身缺陷被修复」）：定向轮产物行带 fix_scope=test 时标注不丢弃、可用 read_fix_out 审计，且标注不影响核销（条目照常 resolved）。出处 tests/test_codefix_targeted_retry.py:492-513、agents/code-fix.md:22（修测试须带 fix_scope=test 标注）、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:51-54 | pass | 0/3 | - |
| targeted-retry-exhausted-discard-archive | 耗尽缺省 3 轮定向重试仍失败 → 现场即弃（4.4/「轮数耗尽现场即弃」）：档案记录含 branch/tip_sha/最后一轮明细引用（detail_ref 文件已落盘）、条目保持 open、worktree 清理（success=False）、链继续推进下一批（批 b 照常合回核销）。出处 tests/test_codefix_targeted_retry.py:515-559、core/code_fix.py:2638-2675（耗尽分支）、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:56-59 | pass | 0/3 | - |
| targeted-retry-map-fail-fallback-full | 映射失败（classname 非 Python 模块形态）→ 回退全量重试 fail-closed（4.5/1.2）：定向轮 subset_nodeids=None 跑全量、明细落盘置 fallback_full=true、全量重试通过仍按通过路径合回核销。出处 tests/test_codefix_targeted_retry.py:564-589、core/code_fix.py:2645-2674（定向轮循环 mapped=False 分支）、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:38 | pass | 0/3 | - |
| targeted-retry-config-guard-and-template | targeted_retry_max 配置守卫与模板键（2.4）：缺省 3；越界（0/9/-1）、非整数（"abc"/None/True/1.5）回退 3；边界值 1 与 5 生效；config.template.yaml 注释键含「targeted_retry_max: 3」与合理区间 1-5 约束。出处 core/config.py:1665-1675 get_code_review_fix_config、.fenix/config.template.yaml:436-444、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:36 | pass | 0/4 | - |
| targeted-retry-prompt-contract-section | code-fix 提示词定向重试契约段（3.1/D3）：失败可能是产品缺陷或测试缺陷、自行判定；只修失败用例相关问题、MUST NOT 扩面重做全批；修测试时产物行必须带 "fix_scope": "test" 字段标注。出处 agents/code-fix.md:17-24（定向重试轮契约段）、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:36 | pass | 0/5 | - |
| targeted-retry-retry-brief-cumulative | 定向轮注入文本与轮间累计明细（2.2/2.3）：注入文本含失败 nodeid+摘要、「MUST NOT 扩面重做全批」硬指令与 fix_scope=test 标注说明；累计合并按 nodeid 去重、后轮摘要覆盖前轮（含此前修过但再次失败的用例）。出处 core/code_fix.py:637-678 _merge_failure_items/_render_targeted_retry_brief、spec/changes/add-codefix-targeted-retry/specs/code-fix-lane/spec.md:39 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

