# fix-verify-late-result-terminal-clobber

## Why

2026-09-24 `fix-quality-gates-flat-form-and-explainability` 实证：机械验证车道 13:59 已把 SPEC 推送到终态 pushed，仍在飞的 LLM verifier（verify-...-a1，42 分钟）14:09 完成后，其结果应用路径命中 stale/foreign 守卫，把终态 pushed 无条件覆写回 implemented，触发 66 秒状态抖动 + 一轮冗余全量重验。同时终态转移未回收在飞 verify 车道，该 run 在推送后仍白烧 10 分钟 LLM tokens。防御纵深两头都缺：迟到结果能覆写终态、终态不回收在飞车道。

## What Changes

- **迟到结果终态丢弃（D6 复核补齐）**：`core/pm_engine/verification/legacy.py` 三个会写状态的结果应用分支（foreign-role/foreign-stamp 分支 ~L137-166、unknown-status+stale 分支 ~L171-196、成功路径 stale 守卫 ~L283-304）在 update_spec 前补「当前状态非 testing 即 DEBUG 丢弃」复核（与同文件 bug-found/verified/进程失败分支既有 D6 判据同构），迟到结果不得覆写任何非 testing 状态、不再触发 re-dispatch 与 infra 记账。
- **终态收敛点回收 verify 车道**：`core/pm_engine/engine.py` 的 `_on_spec_verified` 收敛点（legacy.py:497 与 pipeline.py:1029 双路汇合处）新增车道自我收尾：摘除在队 verify 条目（`_remove_queued_entry(spec, "verifier")`）并经既有取消原语 `cancel_run(<在飞 run 完整 run 级 id 含 epoch>, by="verify-lane")` 终止在飞 verifier run（照搬 `_stop_parallel_planning` 对 planner-plan 车道的既有范式；取消键 MUST 传完整 run id——裸 `verify-<spec>` 键与轮询环消费键不收敛会静默失效，见 design D2）。
- **机械快道裁决带来源戳**：`core/pm_engine/verification/judge_gate.py` `_all_green_fast_path` 写 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 的 payload 补 `"role": "verifier"`（保留 `mechanical: true`），消除「机械车道产物缺 role 戳 → 读侧一律判不采信」的契约缺口（本次误判土壤）。

## Capabilities

### New Capabilities

- `verify-late-result-terminal-guard`：stale/foreign 结果应用分支的终态丢弃复核。
- `verify-inflight-lane-reclaim`：verified 终态收敛点对在飞 verify 车道的回收。
- `verify-result-stamp-contract`：机械快道裁决产物的来源戳契约。

### Modified Capabilities

（无——本变更不修改既有能力语义，只补防御与契约。）

## Impact

- **代码**：`core/pm_engine/verification/legacy.py`、`core/pm_engine/engine.py`、`core/pm_engine/verification/judge_gate.py`
- **测试**：`tests/test_daemon_lifecycle_races.py`（既有 stale/foreign 用例扩展，见 :753 附近）+ 新增终态回收回归
- **相关但不重叠**：活跃 SPEC `fix-quality-gates-terminal-blindspot`（pushed 终态指纹双盲区，属质量门禁指纹族）；本 SPEC 属「在飞结果 × 终态交互」族，两者互补。
- **行为兼容**：正常轮次（结果应用时 spec 仍 testing）零行为变化；仅非 testing 状态下的迟到结果从「覆写+重派」变为「丢弃」。
