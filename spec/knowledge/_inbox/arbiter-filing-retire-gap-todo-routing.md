# arbiter 立项通道退役与 gaps→todo 路由

## 背景

2026-11-03 两例 arbiter 立项草案连续被 spec-review 否决冻结（`fix-scenario-revision-choice-registration-surface` substantive 桶：前提被现行代码证伪；`fix-escalation-freeze-vs-parallel-admin-race` format 桶：方案主体缺失占位文本）。根因是车道职责越界而非提案质量可调参：框架缺口（裁决注册表、升级竞态等机制面）的修复成文需要设计与产品面裁量，arbiter 调查报告粒度天然不足以成文，其立项产出必然是占位草案闯评审硬门。用户定调车道边界：**arbiter 只修 SPEC 问题，不修框架缺口**。add-arbiter-gap-todo-routing 拆通道、接路由（spec/changes/add-arbiter-gap-todo-routing/）。

## 结论（当前事实，折叠主体）

**`arbiter-proposal-filing` 能力页退役注记**：

- arbiter 立项通道已整体退役：`core/pm_engine/arbiter.py` 的提案消费写点 `_apply_proposals`、目录物化 `_materialize_proposal`、节流常量 `PROPOSAL_MAX_PER_RUN` / `PROPOSAL_WEEKLY_QUOTA` 及两处调用点（原 :1027 / :1189）全部删除；台账 kind `spec-proposed` / `proposal-dedup` / `proposal-throttled` 不再产生。该页规则（先物化后注册、物化失败跳过立项、重放幂等、提案最小成文）全部随通道退役失效——无写点即无物化语义可约束。台账 append-only，存量 `spec-proposed` 条目原样保留不清洗。
- 该页保留价值仅剩历史追溯：幽灵条目缺陷形态（无目录 STATE 条目对用户不可见、spec-review 以 rejected（format）收口）的教训对其他任何 STATE 注册写点仍适用（先物化后注册是通用纪律，不是 arbiter 特有契约）。

**`arbiter-lane` 能力页改写素材（立项节流→禁立项红线）**：

- 权限红线新增第 6 类：**MUST NOT 立项**——arbiter 不创建、不注册任何 SPEC（无 `spec/changes` 目录物化、无 STATE 条目写入）。既有白名单处置面（解冻/重验/载荷落地/陈锁清扫/分拣提交）不受扰，红线只收走立项。
- 框架缺口发现（机制/车道/注册表/代码面缺陷，修复涉及框架代码或产品面变更）的出口是调查报告 `gaps` 数组（替代 `proposals`，同 commit 切换无过渡双字段）：逐条按「可直接起草 SPEC」粒度填写 topic/evidence/impact/candidates。消费端 `_apply_gaps` 逐条记 `.fenix/todo.md`，由自进化车道按既有 todo 消费机制统一评估立项——todo.md 是框架缺口的唯一出口。
- todo 条目契约：复用自省渲染单源 `SelfReviewScheduler._render_entry_lines`（四字段标签与 evolution 解析侧逐字一致，MUST NOT 新增第五字段），标题带 `[arbiter:<签名前8>]` 来源前缀、证据段带触发 run_id，落「### 可改进」小节；读写整段置于 fs_utils `with_file_lock`（与 self_review/evolution 共用同一把 `.todo.md.lock`）。
- 台账 kind 演进：记 todo 与去重跳过均落 `gap-noted`（action_or_upgrade 含 topic 与行号/已存在条目指引）；切换窗内旧 prompt run 产出带 `proposals` 字段时记 WARNING 台账（gap-noted 附退役说明）后丢弃，不落 todo 不落池、不抛异常。
- 记 todo 前做轻量同主题去重：主题词（空白/连字符/下划线切分、长度≥2）任一命中既有条目标题（去 `[]` 来源前缀后）即跳过——宁轻勿重，误跳可由台账人工补、重复可由自省合并。并发写测试的 topic 入参须彼此零共享 token，否则会被该去重按设计跳过（这是 D3 既定行为不是锁失效）。

## 证据

- 实现：`core/pm_engine/arbiter.py`（`_apply_gaps` / `_note_gap_todo` / `_render_gap_entry_lines` / `_todo_topic_hit` / `_todo_block_insert`；退役符号 grep 零残留）；`agents/arbiter.md`（红线段 3 与 gaps 上报纪律段、报告 schema `"gaps"` 字段）。
- 测试：`tests/test_arbiter_lane.py` `TestFilingRetirement` / `TestGapTodoRouting` / `TestGapPromptConsumerConsistency`（退役断言/路由断言/契约一致性），`tests/test_arbiter_guardrails.py` prompt 断言改写 + 旧立项用例移除；62 用例全绿。
- 实现期修复一处上一中断 run 遗留缺陷：`GAP_TODO_SECTION` 原为裸 `可改进`，而 `core/evolution.py parse_todo_entries` 的小节正则只认 `### ` 前缀行（`self_review._append_todo` 写入侧为 `### {section}`），裸小节下条目 section 为空被收集面跳过——路由落盘但自进化消费链断链、arbiter 自家 dedup 也失灵。修为 `### 可改进` 与写入侧逐字一致。
- SPEC 溯源：spec/changes/add-arbiter-gap-todo-routing/（proposal/design D1-D5/specs/arbiter-lane delta）。
