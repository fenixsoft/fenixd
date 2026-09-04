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
        screenshots/           # 场景截图（含失败截图）
        <spec>.json            # 场景逐条进度
    runs/              # Agent 运行记录（JSONL 流式）
      impl-<spec>-*.jsonl       # 实现者 run 事件
      verify-<spec>-*.jsonl     # 验证者 run 事件
      admin-*.jsonl             # Administrator 处置 run
      ...                       # 其它 agent 类型
    logs/              # 框架日志
      fenixd-<year>.log         # daemon 滚动日志
    admin_alerts.json  # 告警与处置记录
    admin_invoke_request.json   # Admin 唤起请求信号（daemon 拾取后清除）
    todo.md            # 当日待办/自省列表
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
- status: ready            # 生命周期状态（10 个之一）
- priority: 5              # 优先级 1-9（P1 最高）
- created: <ISO 8601>      # 创建时间
- updated: <ISO 8601>      # 最近更新时间
- implementer_run: <run-id|null>   # 最近实现者 run ID
- tester_run: <run-id|null>        # 最近验证者 run ID
- branch: <branch|null>    # 当前/最近 worktree 分支
- error: <msg|null>        # 错误信息（阻塞原因/冻结原因）
- depends_on: <null>       # 依赖的其它 spec
- total_duration: <null>   # 累计时长
- frozen: <true|false>     # 是否人工冻结
- _impl_run_budget_used: N # 实现尝试预算已使用次数（内部字段）
- _retry_count: N          # 重试计数（内部字段）
- _merge_streak: N         # 连续 merge 失败计数（内部字段）
- _token_warn_80: <bool>   # token 预算 80% 告警已发标记
- _token_alert_100: <bool> # token 预算 100% 告警已发标记
```

> 状态取值与转移规则见 [SPEC 生命周期与状态机](03-lifecycle.md)。

## SPEC artifacts 与 Deliverables 声明段

proposal.md、design.md、tasks.md 与 specs/ 是 spec-driven 流程的 change artifacts。其中 tasks.md 的 **Deliverables** YAML 段声明「本 change 交付/修改哪些文件」，是收工守卫（deliverable gate）的判据——遗漏的新交付文件会被守卫拦截。tasks.md 中 `- [x]` 勾选状态即任务进度，`/fenix-process` 与 Dashboard 读取的都是它。

## .fenix/runs/ 运行记录

每条 run 对应一个 `<agent>-<spec>-<timestamp>.jsonl` 文件：`impl-` 前缀是实现者（含 fast-track），记录每次 tool_use、消息与结果；`verify-` 前缀是验证者。排查「最近一次 run 在做什么」时，按文件 mtime 排序找到最新的 jsonl，看最后几条事件即可。

## 出问题去哪查对照表

| 现象 | 查哪里 |
|------|--------|
| SPEC 状态/优先级 | `.fenix/STATE.md` 该 spec 条目 |
| SPEC 卡在 ready 不派发 | `.fenix/logs/fenixd-<year>.log` 的 dispatch 记录 |
| 实现进展 | `.fenix/runs/impl-<spec>-*.jsonl` 尾部事件 |
| 验证结果 | `.fenix/verify-progress/<spec>/report.json` + verification-report.md |
| 场景失败截图 | `.fenix/verify-progress/<spec>/screenshots/` |
| 告警与自动处置 | `.fenix/admin_alerts.json` |
| Administrator 时间线 | Dashboard「运维记录」页 / admin_alerts.json disposition 记录 |
| daemon 日志 | `.fenix/logs/fenixd-<year>.log` |
| 项目事件时间线 | `.fenix/PROJECT_LOG.md` |
| 当日待办/自省 | `.fenix/todo.md` |
| 任务进度 | `spec/changes/<spec>/tasks.md` 勾选状态 |

## 相关文档

- [Dashboard 使用指南](07-dashboard.md) — 图形界面看同一份数据
- [验证体系](05-verification.md) — 验证产物语义
- [FAQ 与故障排查](10-faq.md) — 按现象直连处置
