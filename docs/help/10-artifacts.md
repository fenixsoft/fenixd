# 文件与数据地图

排查问题时，第一步是知道各种状态、记录、日志分别存在哪里。本章给出 Fenix 项目的完整文件地图，以及一张「出问题去哪查」的对照表。

## 项目根目录

```
<project-root>/
  .fenix/              # 框架运行目录（可安全重生成）
    config.yaml        # 项目级配置（覆盖用户级 ~/.fenix/config.yaml）
    STATE.md           # 所有 SPEC 的状态与元数据
    verify.yaml        # 验证契约（prepare/serve/ready）
    verify-progress/   # 验证产物
      <spec>.json      # 该 spec 验证进度摘要
      <spec>/          # 每个 spec 的验证目录
        report.json            # 验证报告（summary + scenarios）
        test_scenarios.json    # 冻结的验证场景清单
        parallel_plan.json     # 并行出题状态机（dispatched→completed/failed/cancelled/frozen→consumed）
        fastlane_decision.json # fastlane 准入/回落判定记录
        quality-gates.json     # 质量门禁落盘三项（嵌套 {"gates":...} 形态唯一合法）
        verdict_cache.json     # judge verdict 指纹缓存（修复轮裁剪重验范围）
        screenshots/           # 场景截图（含失败截图）
        <spec>.json            # 场景逐条进度
    runs/              # Agent 运行记录（JSONL 流式）
      impl-<spec>-*.jsonl       # 实现者 run 事件
      verify-<spec>-*.jsonl     # 验证者 run 事件
      admin-*.jsonl             # Administrator 处置 run
      evo-*.jsonl               # 框架自进化分析 run 事件（自托管时）
      ...                       # 其它 agent 类型
    logs/              # 框架日志
      fenixd.log         # daemon 滚动日志（10MB×5 轮转，格式见日志体系章）
    architecture/      # 项目架构图产物（gitignored，按项目存自包含 HTML）
    scheduling_kick/   # 即时唤醒信号目录（每 SPEC 一文件，消费后删除）
    code-review/       # 周期代码审查与自动修复产物
      items.jsonl              # 审查问题台账（open/in_spec/resolved/ignored）
      out-<run_id>.jsonl       # 审查 run 逐文件结果
      out-<run_id>-b<N>.jsonl  # code-fix 修复分片产物（批内并行，单写者落盘）
      fix-progress.json        # 自动修复批次进度
      fix-deferred.json        # WIP defer 台账（90min/6 次双门预算）
      fix-failed.json          # 批失败档案（fail_count 预算，达 3 告警）
      code_review_request_result.json  # 手动触发受理回链凭据（started/dropped/failed）
    admin_alerts.json  # 告警与处置记录
    hook_audit.jsonl   # hook 触发与执行审计（append-only）
    admin_invoke_request.json   # Admin 唤起请求信号（daemon 拾取后清除）
    spec_delete_request.json    # SPEC 删除受理信号（有在跑 agent 时异步停止）
    code_fix_request.json       # 手动「自动修复」整链授权信号（消费后清除）
    restart_history.jsonl       # 自愈重启历史（ts / self_triggered / streak）
    supervisor_fused            # supervisor 启动失败熔断标记（人工删除后重启恢复）
    supervisor_runtime.json     # supervisor 运行时自报（pid / script_hash / started_at）
    todo.md            # 当日待办/自省列表
    evolution/         # 框架自进化产物（gitignored，非交付物）
      items.jsonl      # 条目状态机（一行一条，按 id 幂等更新）
      state.json       # 逐项目分析水位（last_analyzed_at / last_run_id）
      drafts/<id>/     # 暂存 SPEC 草稿（接受后移出至 spec/changes/）
      out-<run_id>.json        # 分析 run 契约产物（读取后删除）
    PROJECT_LOG.md     # 项目日志（事件时间线）
  spec/                # SPEC 工作区
    changes/           # 活跃 change
      <spec>/          # 一个 SPEC
        proposal.md    # 需求背景
        design.md      # 详细设计
        tasks.md       # 任务清单（- [x] 进度）
        specs/         # 能力规格（help-docs/spec.md 等）
        verification-report.md  # 验证报告 Markdown
      archive/         # 归档（YYYY-MM-DD-<name>/）
```

## STATE.md 字段逐一解释

每个 SPEC 在 STATE.md 中占一个条目，格式如下：

```markdown
### <spec-name>
- status: ready            # 生命周期状态（11 个之一）
- priority: 5              # 优先级 1-9（P1 最高）
- created: <ISO 8601>      # 创建时间
- updated: <ISO 8601>      # 最近更新时间
- start_after: <ISO8601|manual|null>   # 定时拾取（manual=待人工激活，永不到期）
- frozen_until: <ISO8601|null>         # 定时解冻时刻（到点自动解冻）
- impl_run_budget_override: <int|null> # per-spec 实现尝试预算覆盖（按 agents.impl_run_budget_max 夹紧）
- implementer_run: <run-id|null>   # 最近实现者 run ID
- tester_run: <run-id|null>        # 最近验证者 run ID
- reviewer_run: <run-id|null>      # 最近方案评审 run ID（reviewing 态必有值）
- branch: <branch|null>    # 当前/最近 worktree 分支
- error: <msg|null>        # 错误信息（阻塞原因/冻结原因）
- depends_on: <null>       # 依赖的其它 spec
- total_duration: <null>   # 累计时长
- frozen: <true|false>     # 是否人工冻结
- _review_attempts: N      # 方案评审尝试计数（内部字段，上限 3 次含首次）
- _impl_run_budget_used: N # 实现尝试预算已使用次数（内部字段）
- _retry_count: N          # 重试计数（内部字段）
- _merge_streak: N         # 连续 merge 失败计数（内部字段）
- _token_warn_80: <bool>   # token 预算 80% 告警已发标记
- _token_alert_100: <bool> # token 预算 100% 告警已发标记
```

**内部字段（`_` 前缀）**：所有 `_` 前缀字段**无条件透传持久化**（`core/state_machine.py` 的序列化逻辑），完整集合以 `core/state_machine.py` 为准。可观测的关键项：

| 字段 | 含义 |
|------|------|
| `_verify_redo_count` | 重启重验预算已用次数（`agents.verify_redo_budget`，超限 `verify_redo_exhausted` 冻结） |
| `_verify_fail_rounds` | 验证失败连续轮数（三轮熔断判据） |
| `_frozen_hold` | 冻结保持标记（冻结终止在跑 agent 后置位） |
| `_cancelled_hold` | 取消保持标记（人工取消后的有意等待） |
| `_env_block_rounds` | env 阻塞连续轮数（≥2 轮冻结升级） |
| `_inconclusive_attempts` | env 豁免两级防线共享计数（3 静默重派 / 4 升级） |
| `_infra_failure_count` / `_verify_infra_rounds` | infra 失败观测（不计入冻结判定） |
| `_infra_refunded_run_ids` | infra 验证 run 预算退款幂等清单 |
| `_fastlane_fail_streak` | fastlane 连续失败计数（达 2 回落整轮） |
| `_review_skipped_result` | 评审收尾被并发推进时的结果侧车（`<status>@result-path=<路径>`） |
| `_recovery_resume` | 保留分支续做标记（一次性消费） |
| `_repair_awaiting_remerge` | repair 成功、待重新合并进主树标记 |
| `_merge_retry_pending` | merge-back spec 目录在飞守卫的有界顺延记账 |
| `_judge_rerun_count` | judge 重裁决累计次数（spec 级上限 5） |
| `_impl_gate_task_rejections` | 收工守卫对任务书声明形态的拦截计数 |

> 状态取值与转移规则见 [生命周期与状态机](03-lifecycle.md)。

## SPEC artifacts 与 Deliverables 声明段

proposal.md、design.md、tasks.md 与 specs/ 是 spec-driven 流程的 change artifacts。其中 tasks.md 的 **Deliverables** YAML 段声明「本 change 交付/修改哪些文件」，是收工守卫（deliverable gate）的判据，遗漏的新交付文件会被守卫拦截。tasks.md 中 `- [x]` 勾选状态即任务进度，`/fenix-process` 与 Dashboard 读取的都是它。

## .fenix/runs/ 运行记录

每条 run 对应一个 `<agent>-<spec>-<timestamp>.jsonl` 文件：`impl-` 前缀是实现者（含 fast-track），记录每次 tool_use、消息与结果；`verify-` 前缀是验证者。排查「最近一次 run 在做什么」时，按文件 mtime 排序找到最新的 jsonl，看最后几条事件即可。

## .fenix/evolution/ 自进化产物（gitignored，非交付物）

框架自托管（`PROJECT_ROOT == FRAMEWORK_ROOT`）时，自进化链路（见[配置参考](09-config.md#self_evolution框架自进化)）在 `.fenix/evolution/` 暂存全部中间产物：

| 文件 | 语义 |
|------|------|
| `items.jsonl` | 条目状态机：一行一条（`id` / 原始四字段 / `verdict` / `analysis_md` / `spec` / `status` / `decided_*`）。状态流转 `pending`（待决策）→ `accepted` / `auto_accepted`（已同意/已自动接受）/ `rejected`（已拒绝）；`analyzed`（判定不需要立项）；`draft_failed`（草稿生成失败）；`accept_failed`（接受失败可重试）。对同一 `id` 只保留一条记录（更新而非追加），`id` 集合是去重的权威来源 |
| `state.json` | 逐项目分析水位：`{"<project>": {"last_analyzed_at": "<ISO8601>", "last_run_id": "evo-..."}}`。仅在分析 run 成功落地后推进，且取 run 启动时的快照时刻——只用作检查点触发判据，不承担去重 |
| `drafts/<id>/` | 暂存 SPEC 草稿（proposal.md / design.md / tasks.md / specs/\<capability\>/spec.md / .spec.yaml）。接受后整目录移出交由 `spec/changes/<evo-*>/`（提交并注册 STATE），拒绝时整目录删除；`draft_failed` 的草稿在 lint 未通过时即被删除 |
| `out-<run_id>.json` | 分析 run 的契约产物（`items[]` 含判定与草稿文本），框架读取落地后即删除（与 `self_review_out-*.json` 同处理） |

已接受条目的草稿会**移出暂存区**交给 `spec/changes/`（SPEC 名统一 `evo-` 前缀），草稿暂存区只保留未决定条目；`spec/changes/` 下已注册的 `evo-*` SPEC 走既有流水线（见[生命周期](03-lifecycle.md)），不再与 `.fenix/evolution/` 关联。

## .fenix/spec-review/ 评审运行产物（gitignored，非交付物）

方案评审门禁（见[治理规则](06-governance.md#spec-方案评审门禁)）的评审 run 产物落在 `.fenix/spec-review/<spec>/`：

| 文件 | 语义 |
|------|------|
| `.fenix-run-result.json` | 评审结果契约：`status`（`approved` / `repaired` / `rejected`）+ `findings[]`（每个含 aspect / detail / evidence，`rejected` 必有 `blocking`）+ `repairs[]`（评审者就地修补清单）+ `confidence` |
| `snapshot.json` | 评审派发前的写入边界快照（SPEC 目录文件哈希 + 工作区脏文件哈希），收工后据此做越界检测 |

评审 run_id 前缀 `spec-review-`，流转录在 `.fenix/runs/spec-review-<spec>-<timestamp>.jsonl`。评审相关冻结（`frozen: true`，error 内嵌 `spec-review-rejected:` / `spec-review-incomplete:` 标识）的恢复见[生命周期](03-lifecycle.md#blocked-的两种语义冻结-vs-阻塞)，非冻结历史评审 blocked 条目的重新评审入口见[治理规则](06-governance.md#spec-方案评审门禁)。

## .fenix/regression/ 全量回归产物（gitignored，非交付物）

全量回归车道（`add-test-regression-tab`，执行声明见[配置参考](09-config.md#verifyyaml-的-regression-段全量回归执行声明)）的运行时产物：

| 文件 | 语义 |
|------|------|
| `last-run.json` | 最近一次回归结果快照（**覆盖式单快照**，design D5——首版不保留多轮历史）：`status`（`passed` / `failed` / `timeout` / `parse_error` / `never_run`）+ `cmd` / `output` / `started_at` / `finished_at` / `duration_seconds` / 计数（total/passed/failed/errors/skipped）+ `failures[]`（name/file/line/time/kind/message）+ `long_tests[]`（name/file/line/time）+ `long_test_threshold_seconds` + `reason`（timeout/parse_error 时非空） |
| `state.json` | 周期调度防重状态：`last_run_date`（同一自然日防重；**独立于**自省/code-review 的防重状态文件，design D4） |
| `.running` | 运行中标记（started_at + timeout_seconds，供 `POST /api/regression/run` 的 409 单飞守卫与分面 `running` 字段判定；超窗视为崩溃残留，按未运行处理） |
| `junit.xml` 等 | `regression.cmd` 产出的 JUnit XML（路径由 `regression.output` 声明，随各项目而异） |

信号文件 `.fenix/regression_request.json`（手动触发，dashboard 原子写 → daemon 主循环消费，同 code-review 信号族）在消费后即被清除。

## 出问题去哪查对照表

| 现象 | 查哪里 |
|------|--------|
| SPEC 状态/优先级 | `.fenix/STATE.md` 该 spec 条目 |
| SPEC 卡在 ready 不派发 | `.fenix/logs/fenixd.log` 的 dispatch 记录 |
| 实现进展 | `.fenix/runs/impl-<spec>-*.jsonl` 尾部事件 |
| SPEC 卡在 reviewing | `.fenix/runs/spec-review-<spec>-*.jsonl` 尾部事件 + `.fenix/spec-review/<spec>/.fenix-run-result.json`（评审结果契约）；仍在评审中则看评审 run 是否在跑 |
| SPEC 因评审进 blocked | `.fenix/STATE.md` 该 spec 条目 `frozen: true` + error 字段（内嵌 `spec-review-rejected:` 需人工裁决方案；`spec-review-incomplete:` 需看评审器为什么没跑成；完整格式 `用户指令冻结：原状态 reviewing · …`），见[生命周期](03-lifecycle.md#blocked-的两种语义冻结-vs-阻塞) |
| 验证结果 | `.fenix/verify-progress/<spec>/report.json` + verification-report.md |
| 场景失败截图 | `.fenix/verify-progress/<spec>/screenshots/` |
| 告警与自动处置 | `.fenix/admin_alerts.json` |
| Hook 触发与执行结果 | `.fenix/hook_audit.jsonl`（spec/event/action/status/duration，尾部倒序） |
| Administrator 时间线 | Dashboard「运维记录」页 / admin_alerts.json disposition 记录 |
| daemon 日志 | `.fenix/logs/fenixd.log` |
| 项目事件时间线 | `.fenix/PROJECT_LOG.md` |
| 当日待办/自省 | `.fenix/todo.md` |
| 建议改进项 / 自进化草稿 | `.fenix/evolution/items.jsonl` + `drafts/<id>/`（Dashboard 设置页「自进化」页签） |
| 任务进度 | `spec/changes/<spec>/tasks.md` 勾选状态 |
| 全量回归结果 | `.fenix/regression/last-run.json`（Dashboard 项目页「测试回归」分面）；周期防重在 `state.json` 的 `last_run_date`，手动触发信号见 `.fenix/regression_request.json`，运行中标记见 `.running` |
| 质量门禁卡在哪道门 | `.fenix/verify-progress/<spec>/quality-gates.json`（落盘三项；其余三项框架合成）+ Dashboard 详情页门禁卡 |
| fastlane 是否被采用 | `.fenix/verify-progress/<spec>/fastlane_decision.json`（准入/回落判定与理由） |
| code-fix 台账与修复进度 | `.fenix/code-review/items.jsonl`（台账）+ `fix-progress.json`（批次进度）+ `fix-deferred.json` / `fix-failed.json`（defer 与失败档案） |
| 自愈重启是否自触发循环 | `.fenix/restart_history.jsonl`（`self_triggered` / `self_triggered_streak` 字段） |
| supervisor 是否熔断 | `.fenix/supervisor_fused` 存在即熔断（含失败次数与 pid）；修复后删除该文件并重启 supervisor；运行时自报见 `supervisor_runtime.json` |

## 相关文档

- [Dashboard 操作手册](08-dashboard.md) — 图形界面看同一份数据
- [日志体系](11-logs.md) — 各日志文件的用途、格式、轮转与归档
- [验证体系](05-verification.md) — 验证产物语义
- [FAQ 与故障排查](12-faq.md) — 按现象直连处置
