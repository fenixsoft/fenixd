## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_admin.py
  kind: modify
- path: tests/test_agent_runner.py
  kind: modify
```

> 交付清单以实际改动落点为准：`run_administrator` 定义在
> core/agent_runner/maintenance_runs.py:52（runner.py:956 仅门面转导），Exit 证据装配
> 在该文件 except 分支（:148 附近）；core/agent_runner/runner.py 的 error 归因文本
> 本 SPEC **不改**（见 design 兼容与风险）。
> core/event_bus.py:344 的 pgrep 孪生若随任务 1.5 同步，须追加为 modify 条目。

## 1. 落地校验

- [x] 1.1 core/admin_monitor.py：`_spec_from_run_id`（:2352）的 spec 名归一改用真源全量前缀 `core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES`（顺序与真源一致，含 `repair-`），对 `repair-<spec>-<ts>[-a<n>|-r<n>]` 正确还原 spec 名
- [x] 1.2 core/admin_monitor.py：失败计数前缀子集保留独立常量且**保留名 `_RUN_PREFIXES`**（tests/test_dashboard_data.py:586、tests/test_deliverable_declaration_triage.py:423,450 直接 import），子集补入 `repair-`，`planner-`/`test-` 仍不计入；`_detect_repeated_failures`（:782，解析在 :800）计数语义与设计 1 一致
- [x] 1.3 core/admin_monitor.py：`_has_recent_spec_run`（:357）覆盖 `repair-` 前缀 run 文件活跃度（mtime 在 ORPHANED_RUN_GRACE_SECONDS=120 内即非孤儿）——spec_is_undriven（:384）条件 ① 不再对 repair 活跃期恒假
- [x] 1.4 core/admin_monitor.py：`_pgrep_live_worktree`（:335）模式集加入 `repair`（`repair-<spec>-`），使条件 ② 覆盖 repair worktree（core/worktree_manager.py:3479 目录名 `repair-<spec>-<ts>`）；同步 core/event_bus.py:344 孪生或将 event_bus 该处改为复用同一函数
- [x] 1.5 core/agent_runner/maintenance_runs.py：`run_administrator` 非零退出的失败证据附四项——`getattr(e,"stderr_lines",[])` 末 N 行原始 stderr（截断 4KB）、`getattr(e,"exit_code",None)`、run 产物内 `provider_marker` 的 provider/model、run 末 **3 条带 timestamp 的事件**时间戳（MUST 跳过无 timestamp 的 error/stderr/result/provider_marker/system 事件）；原始 stderr 只进独立证据字段，**不得**回填 `error` 归因文本（保持 error-attribution-denoise D5 语义）
- [x] 1.6 core/admin_monitor.py：告警 description/注释区分 orphaned_state 的 signal / disposition pending / disposition failed / escalated 阶段；文档只描述阶段差异，不声称「同一信号仅一条记录」（冷却过期后成条属既有 `_throttled` 语义，:1242-1247）

## 2. 测试

- [x] 2.1 tests/test_admin.py：新增用例——repair- 前缀 run 活跃时 `spec_is_undriven` 返回 False（本次误报回归用例，夹具对应 `repair-<spec>-<ts>`）；不活跃且无存活进程、无待派发时仍返回 True
- [x] 2.2 tests/test_admin.py：新增用例——`_spec_from_run_id` 覆盖 repair-/impl-/verify-/planner-plan-/planner-judge-/spec-review-/admin-/dispute-judge- 全前缀（含 `-a<n>` / `-r<n>` 后缀）
- [x] 2.3 tests/test_admin.py：新增用例——`_pgrep_live_worktree` 对 `repair-<spec>-<ts>` worktree 进程判定为存活（pgrep 调用打桩）
- [x] 2.4 tests/test_admin.py：新增用例——前缀语义拆分锁定：失败计数子集含 `repair-`、不含 `planner-`/`test-`；`repeated_failures` 不因归一改用全量前缀而纳入 planner-/test- 失败 run
- [x] 2.5 tests/test_agent_runner.py：新增用例——`run_administrator` 退出非 0 时失败证据含原始 stderr 摘录、退出码、provider/model 与带时间戳事件时间线，且 `error` 文本仍为降噪后形态
- [x] 2.6 回归实测：tests/test_dashboard_data.py、tests/test_deliverable_declaration_triage.py 两条同源哨测试在任务 1.1/1.2 后保持绿色（无需改动即通过，须实跑确认而非推断）
