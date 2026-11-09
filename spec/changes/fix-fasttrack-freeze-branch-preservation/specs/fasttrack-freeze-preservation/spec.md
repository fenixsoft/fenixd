# Spec：fasttrack-freeze-preservation

## 背景与目标

fast-track 车道重试耗尽冻结转人工时实现分支/现场未保全（single-app-realdevice-retest 2026-11-09 事故：13 个已验证提交险随 `git gc` 全丢）。本能力确立「冻结即保全 + 清理守护」两道防线，使冻结现场始终可续做。

## 需求

### R1 冻结即保全（MUST）

fast-track 重试耗尽冻结（`core/pm_engine/dispatch/fast_track.py` 两处 `freeze_for_human` 站点 ≈:1079 与 ≈:2168）在冻结前 MUST 对实现现场执行保全：实现分支相对解析基线（`resolve_base_branch`）存在未合并提交时，产生 pre-rmtree snapshot（沿用 `core/worktree_manager/lifecycle.py:1283` 既有快照语义）并保留分支，置 `_frozen_hold: True` 并在同一原子窗口回写 STATE `branch`/`implementer_run` 锚点（`.STATE.md.lock` 内最新条目复核，与 unfreeze_spec 同口径）。分支解析 MUST 复用 `_resolve_preserved_branch` 同源三层口径，MUST NOT 另持平行副本。保全失败 MUST NOT 阻断冻结（fail-open + ERROR 审计）。零未合并提交时 MUST 退化为现状行为（不置 hold、不产快照）。重复保全 MUST 幂等。

### R2 告警证据（MUST）

重试耗尽人工升级告警的 `evidence` MUST 并入保全摘要（分支名、ahead 提交数、snapshot 有无、hold 置位结果），使值守方无需 fsck 即可知现场可续做。

### R3 清理守护（MUST）

所有可删除 `fenix/<spec>-<ts>` 实现分支或 spec worktree 的清理入口（实现期全量定位，含 `core/worktree_manager/stale_sweep.py`、`core/worktree_manager/lifecycle.py` 遗产处置/分支删除段）对 `frozen=True` 且 `_frozen_hold: True`（或保全登记在册）的 spec MUST 跳过删除并 WARNING 留痕。守卫 MUST NOT 引入新锁序。

### R4 续做闭环（MUST）

R1 现场经 `unfreeze_spec` 解冻 MUST 命中既有 `_resolve_preserved_branch` 续做通道：`_recovery_resume: True`、branch/implementer_run 锚点保留、`_frozen_hold` 清零、dispatch 在保全分支上续做而非从零新建。本能力 MUST NOT 改动 `_resolve_preserved_branch`/`unfreeze_spec` 契约本身。

## Scenario

### S1 事故复现→保全生效（对应 R1/R2，验收任务 4.1）

给定 fast-track run 诚实申报 partial 且分支含 N>0 个未合并提交，当重试 max_retries 轮耗尽触发冻结，则冻结完成后：分支存在且提交完好、STATE `_frozen_hold: True` 且 `branch` 非空、存在 `pre-rmtree snapshot` 快照提交、告警 evidence 含保全摘要。

### S2 冻结→解冻→续做（对应 R4，验收任务 4.1）

对 S1 现场 `unfreeze_spec(spec, status='implementing')`，则 `_recovery_resume: True`、branch/implementer_run 保留、`_frozen_hold` 清零，续做解析命中保全分支。

### S3 清理守护（对应 R3，验收任务 4.2）

对 S1 现场驱动 stale sweep 与遗产清理入口，则分支与 worktree 均不被删除，且留有跳过 WARNING。

### S4 零提交退化（对应 R1 退化条款，验收任务 4.3）

给定分支无未合并提交的 fast-track 重试耗尽冻结，则不置 `_frozen_hold`、不产快照，冻结行为与告警与现状一致（evidence 无保全摘要或明确标注零提交）。

### S5 保全失败不阻断冻结（对应 R1 fail-open 条款，验收任务 4.3）

给定保全步骤注入 IO 异常，则冻结本身成功完成（blocked+frozen+告警），ERROR 审计留痕存在。

## Deliverables

- path: core/pm_engine/dispatch/fast_track.py
  kind: modify
- path: core/worktree_manager/stale_sweep.py
  kind: modify
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: tests/test_fasttrack_freeze_preservation.py
  kind: new
