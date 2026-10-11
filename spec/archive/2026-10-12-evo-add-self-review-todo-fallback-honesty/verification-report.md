# 验证报告：evo-add-self-review-todo-fallback-honesty

> ⚠️ 本报告由框架于 2026-10-04T19:22:48Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-04T19:22:48.339176+00:00+run-result@mtime1791141768363595646

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.17M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| todo-off-injects-not-collected-statement | 组装侧未收集态（read_todo=false）：.fenix/todo.md 实存近3日窗口内条目时，调度器传给 run_self_review 的第 4 参为显式未收集陈述「（read_todo 关闭，未收集既有条目）」，不含空窗口文案「（近3日窗口内无既有条目）」、不含未收集条目 ID（未收集≠收集为空）；回归点：todo_md 全文（第 3 参）不注入、既有条目不被 resolved 移除（出处 core/self_review.py:1143、1277；core/agent_runner/maintenance_runs.py:575） | pass | 0/8 | - |
| todo-on-empty-window-verdict-kept | 组装侧空窗口态（read_todo=true 且 todo.md 不存在、窗口内确无条目）：注入保持「（近3日窗口内无既有条目）」真收集结论，且该文案不含 read_todo 归因字样、与未收集陈述可分辨（出处 core/self_review.py:1277-1281、render_todo_entries 空清单分支 :1149） | pass | 0/6 | - |
| todo-on-entries-id-list-injected | 组装侧有条目态（read_todo=true 且窗口内存在既有条目）：注入带 ID 标注清单（含日期节「## 2026-09-04」、小节「### 浪费」与「[2026-09-04#浪费#1]」条目行），行为与现状一致；todo_md 全文同步注入、不含未收集陈述（出处 core/self_review.py:1280-1281、render_todo_entries :1146） | pass | 0/7 | - |
| states-copy-distinguishable-constants | 文案可分辨性与空清单渲染回归：常量 TODO_ENTRIES_NOT_COLLECTED 与空窗口文案互不相等、互不包含（未收集陈述含 read_todo 归因、空窗口文案不含）；render_todo_entries([]) 保持「（近3日窗口内无既有条目）」不变，非空清单渲染含 ID 行（出处 core/self_review.py:1139-1157） | pass | 0/8 | - |
| prompt-not-collected-passthrough | prompt 组装侧未收集态透传：detail.todo_entries=显式未收集陈述时，self-review prompt 的 {todo_entries} 段渲染该陈述原样，无 {todo_entries} 占位符残留、不含空窗口文案（出处 core/agent_runner/prompt_builder.py:1674-1675；agents/self-review.md:13） | pass | 0/4 | - |
| prompt-empty-window-passthrough | prompt 组装侧空窗口态透传：detail.todo_entries=空窗口文案时原样渲染，无占位符残留、不含未收集陈述——两种真实状态在同一兜底点互不污染（出处 core/agent_runner/prompt_builder.py:1674-1675） | pass | 0/4 | - |
| prompt-unexpected-empty-fallback-narrowed | prompt or-fallback 收窄（异常路径）：detail 缺 todo_entries 键或值为空串时，落新兜底「（意外空值：既有条目清单未提供）」，不再复用空窗口文案「（近3日窗口内无既有条目）」、也不误报 read_todo 未收集（出处 core/agent_runner/prompt_builder.py:1674-1675） | pass | 0/6 | - |
| prompt-todo-md-fallback-unchanged | {todo_md_content} 兜底回归（tasks 1.2 后半）：detail 缺 todo_md 时兜底保持「（read_todo 关闭或 todo.md 不存在，不注入）」不变；todo_md 有值时原样注入、无占位符残留（出处 core/agent_runner/prompt_builder.py:1667-1668） | pass | 0/5 | - |
| run-self-review-normalization-preserves-statement | 归一透传：maintenance_runs.run_self_review 的 todo_entries or "" 归一把显式未收集陈述非空透传进 detail（不被吞成空串）；None（历史调用方形态）仍归一空串、落意外空值兜底而非伪结论（出处 core/agent_runner/maintenance_runs.py:571-575） | pass | 0/4 | - |
| delivered-fallback-tests-green | 本 SPEC 新交付测试文件全绿：tests/test_self_review_todo_fallback.py 7 例 PASSED（组装侧三态、文案可分辨、prompt 两态透传断言）（出处 tests/test_self_review_todo_fallback.py） | pass | 0/7 | - |
| daily-self-review-regression-green | 既有 daily 套件回归全绿：tests/test_daily_self_review.py 70 例 PASSED，含按新兜底改断言的 test_todo_entries_default_when_absent、改显式陈述断言的 test_read_todo_off_no_removal，与不受影响的 render 空清单断言（出处 tests/test_daily_self_review.py:1489、1219、1101） | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

