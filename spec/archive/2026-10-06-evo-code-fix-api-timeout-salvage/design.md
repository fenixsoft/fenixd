# design: code-fix-api-timeout-salvage

## D1 签名判别点：runner 层挂标记

core/agent_runner/runner.py 的 _run_claude 非 0 退出分支（约 :5047-5066，失败异常已携带 stderr_lines/has_result/exit_code）判别 api_timeout（末次 result 事件 terminal_reason=="api_error"，或 result 文本命中 "Request timed out"），把布尔标记挂到失败异常上。判别在 runner 层一次完成，车道层只读标记。
备选：在 maintenance_runs 层重新解析归档判别——否，重复解析 result 事件且时点更晚。

## D2 salvage 挂点：失败当时而非陈旧清扫期

现场核查显示 Pre-rmtree 快照产生于失败约 2 小时后的 stale sweep（lifecycle.py:664，调用点 stale_sweep.py:99），彼时消化链已推进多批，快照注定悬空。本设计把救回前移到失败当时：core/code_fix.py 的 _run_batch_created（:3170）失败分支（现直接调 _safe_cleanup，调用点 :3195）在命中 api_timeout 且工作区脏时改走 salvage 路径。

## D3 复用既有 salvage 与 legacy 基础设施

- 提交：复用 _salvage_commit（core/code_fix.py:1711，add-codefix-commit-first-contract 已交付，tests/test_code_fix_salvage.py 有编排侧范本），不新增提交机制。
- 保全：登记 recovery legacy（core/worktree_manager/legacy_registry.py），宽限期内豁免陈旧清扫（stale_sweep.py:46-52 既有语义）。
- 接续：salvage commit 后对 "code-review-fix"（批建树既有 spec_name，code_fix.py:3134）调用 mark_legacy_reusable（legacy_registry.py:103）置 reuse 标记；下一批建树（_run_batch_inner 的 wm.create，约 :3134）经 create 内既有认领通路 _take_reusable_worktree（lifecycle.py:166 → legacy_registry.py:217）继承批分支上的 salvaged 提交（仅分支模式在既有分支上重建载体，MUST NOT 从 main HEAD 起新分支）。MUST NOT 在建树前调用 consume_legacy——其语义是「后继成功 merge 后回收」（出册 + worktree remove --force + branch -D，legacy_registry.py:79-97/358-399），建树前调用会删掉承载 salvaged commit 的分支，复刻本提案要解决的悬空 commit 净损失。现状口径：code-fix 失败清理路径（cleanup success=False，lifecycle.py:513/521-531）对非 verify- 前缀分支本就自动登记 legacy（只登记、无人置 reuse、无人认领），本设计增量是 salvage commit + reuse 标记，认领端零新增（create 既有通路）。

## D4 非 api_timeout 失败行为不变

保持 add-code-fix-batch-failure-selfheal 的「失败=chain_skipped 跳批推进」与确定性失败重试预算语义；只有 api_timeout 签名改变清理时序。

## 非目标

run_stall_budget 不动（core/config.py:234 缺省 False 维持）；spec 车道原位重试、Pre-rmtree 快照机制、熔断/瞬态判据均不动。

## 风险

- legacy 认领与下一批建树的竞态：认领不可用（无 legacy/载体失效/换壳失败）时 create 既有通路 fail-open 回退全新建树（Requirement 3 的 AND 子句），不阻断链推进。
- salvage commit 落批分支后，重试批可能重复修同一条目：salvage 不改变条目核销状态（与 add-code-fix-item-level-progress 口径对齐），重复成本由台账核销去重兜住。