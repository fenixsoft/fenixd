# design: code-fix-api-timeout-salvage

## D1 签名判别点：runner 层挂标记

core/agent_runner/runner.py 的 _run_claude 非 0 退出分支（约 :5047-5066，失败异常已携带 stderr_lines/has_result/exit_code）判别 api_timeout（末次 result 事件 terminal_reason=="api_error"，或 result 文本命中 "Request timed out"），把布尔标记挂到失败异常上。判别在 runner 层一次完成，车道层只读标记。
备选：在 maintenance_runs 层重新解析归档判别——否，重复解析 result 事件且时点更晚。

## D2 salvage 挂点：失败当时而非陈旧清扫期

现场核查显示 Pre-rmtree 快照产生于失败约 2 小时后的 stale sweep（lifecycle.py:664，调用点 stale_sweep.py:99），彼时消化链已推进多批，快照注定悬空。本设计把救回前移到失败当时：core/code_fix.py 的 _run_batch_created（:3170）失败分支（现直接 _safe_cleanup，:3519）在命中 api_timeout 且工作区脏时改走 salvage 路径。

## D3 复用既有 salvage 与 legacy 基础设施

- 提交：复用 _salvage_commit（core/code_fix.py:1711，add-codefix-commit-first-contract 已交付，tests/test_code_fix_salvage.py 有编排侧范本），不新增提交机制。
- 保全：登记 recovery legacy（core/worktree_manager/legacy_registry.py），宽限期内豁免陈旧清扫（stale_sweep.py:46-52 既有语义）。
- 接续：同链下一批建树（_run_batch_inner 的 wm.create，约 :3134）前调用既有 consume_legacy（legacy_registry.py:79）；code-fix 车道目前只登记不消费，本设计接上消费端。

## D4 非 api_timeout 失败行为不变

保持 add-code-fix-batch-failure-selfheal 的「失败=chain_skipped 跳批推进」与确定性失败重试预算语义；只有 api_timeout 签名改变清理时序。

## 非目标

run_stall_budget 不动（core/config.py:234 缺省 False 维持）；spec 车道原位重试、Pre-rmtree 快照机制、熔断/瞬态判据均不动。

## 风险

- legacy 消费与下一批建树的竞态：consume_legacy 失败须 fail-open 降级为现状行为（Requirement 5 的 AND 子句）。
- salvage commit 落批分支后，重试批可能重复修同一条目：salvage 不改变条目核销状态（与 add-code-fix-item-level-progress 口径对齐），重复成本由台账核销去重兜住。