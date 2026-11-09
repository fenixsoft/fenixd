# Tasks：fast-track 冻结实现分支现场保全

依赖序：1（调查定位）→ 2/3（两道防线，可并行）→ 4（回归与验收）→ 5（知识沉淀）。

## 1. 调查定位

- [x] 1.1 精确定位 single-app 事故形态下实现分支的实际删除者：以 `core/pm_engine/dispatch/fast_track.py:693`（`_keep_fast_track_worktree` 保留）与 `core/worktree_manager/stale_sweep.py`、`core/worktree_manager/lifecycle.py:839-1012`（register_legacy 遗产保留/branch -D 段）、`:1283`（pre-rmtree snapshot）为起点，穷举冻结后仍能删 `fenix/<spec>-<ts>` 分支或 spec worktree 的全部入口，输出调查结论（入口清单 + 删除时序 + 为何未产快照）写入本 spec 目录 `findings.md`；结论直接支撑任务 2/3 的接线点选择

## 2. 防线一：冻结即保全

- [x] 2.1 实现保全助手（preserve-before-freeze，见 design.md 防线 1 契约）：三层分支解析复用 `_resolve_preserved_branch` 同源口径、rev-list 非空闸门、pre-rmtree snapshot 复用 `core/worktree_manager/lifecycle.py:1283` 语义、`_frozen_hold: True` + `branch`/`implementer_run` 锚点 `.STATE.md.lock` 内原子回写、幂等、fail-open ERROR 审计；接线 `core/pm_engine/dispatch/fast_track.py` 全部四处冻结站点（≈:1076 契约违反 / ≈:1308 硬校验失败 / ≈:2165 通用失败 / ≈:2300 零变更哨）在 `freeze_for_human` 之前调用，并把保全摘要并入告警 evidence（R1/R2）；`_frozen_hold` 与锚点回写 MUST 同一原子窗口（扩展 `mark_frozen_hold` 新参数可选缺省且其余调用点逐位不变，或助手单次锁定写覆盖全部字段）
- [x] 2.2 实现期若判定保全逻辑应在冻结入口内聚（freeze_for_human 增可选保全回调），允许替代 2.1 的站点外置接线，但 MUST 保持其余 freeze_for_human 调用点行为逐位不变，并在 2.1 同一提交内说明选择依据

## 3. 防线二：清理守护

- [x] 3.1 依据 1.1 的入口清单，为全部可删实现分支/spec worktree 的清理入口（含 `core/worktree_manager/stale_sweep.py` 与 `core/worktree_manager/lifecycle.py` 遗产处置段）加守护：spec `frozen=True` 且 `_frozen_hold: True`（或保全登记在册）时跳过删除并 WARNING 留痕；守卫走一次性 STATE 读取，不引入新锁序（R3）

## 4. 回归测试与验收

- [x] 4.1 新建 `tests/test_fasttrack_freeze_preservation.py` 覆盖 S1 事故复现（冻结后分支/hold/锚点/快照/告警 evidence 断言）与 S2 解冻续做闭环（`_recovery_resume: True`、锚点保留、hold 清零）（R1/R2/R4）
- [x] 4.2 同文件覆盖 S3 清理守护：对保全现场驱动 1.1 清单中的清理入口，断言不删 + WARNING（R3）
- [x] 4.3 同文件覆盖 S4 零提交退化与 S5 保全 IO 异常不阻断冻结（R1 退化与 fail-open 条款）

## 5. 知识沉淀

- [ ] 5.1 更新知识页：recovery-continuity 域补「fast-track 冻结即保全」条目（不变量、接线点、守护清单）；worktree-vc 域补「冻结 spec 分支删除守卫」口径；如 1.1 发现与本文档根因模型不符，以 findings.md 为准回写 design.md 根因模型段
