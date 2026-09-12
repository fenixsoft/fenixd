## Context

`tests/test_cancel_holdstate_recovery.py` 的 `CancelFinalizeMarkerContract.WRITE_POINTS` 以**绝对行号**钉住六处取消收尾写点，断言以行号为中心的 ±8/+6 邻域窗口内出现 `"_cancelled_hold": True` 与 `"error": cancelled_err`。

fenixd 高频并行分支合并不断在被测文件（`dispatch.py` / `verification.py`）插入行，写点行号随之漂移。已发生三次手工重钉（14380774、2e98e052、762b4aee），2e98e052 还带出 4/6 子用例红灯；当前（2026-09-12）verification.py 三处写点已漂移到 1629/2003/2836，测试 3/6 红灯且无人发现。

约束：不引入外部依赖；被测文件运行时逻辑一字不改；无 UI、无数据迁移。

## Goals / Non-Goals

**Goals:**

- 写点断言对行号漂移**免疫**——定位改为运行时动态重算。
- 失配即红且报错含「label / 锚点串 / 当前命中情况」，自检内化，无需 daemon/hook 层改造。
- 保留「恰好六处写点」的唯一性自证（防止漏新增/锚点误命中）。

**Non-Goals:**

- 不改 `core/pm_engine/dispatch.py`、`core/pm_engine/verification.py` 的运行时逻辑。
- 不做 daemon 晋升 lint 或合并 hook 层的 post-merge 自检（等价能力由测试运行时自检覆盖）。
- 不把定位函数抽成通用测试框架（仅此测试使用，YAGNI）。

## Decisions

### D1: 锚点串 = 每条写点最近的「人工取消 hold-state（add-run-cancel D4…）」取消分支注释

每条写点对应的锚点串取写点**前向最近**、且在其文件内**唯一**的取消分支注释字面（已逐条 `grep -F` 核验恰好命中 1 次）：

| label | 文件 | 锚点串（字面） | 锚点行 | 写点 `_cancelled_hold` 行 | 偏移 |
|---|---|---|---|---|---|
| implementer | dispatch.py | `人工取消 hold-state（add-run-cancel D4）` | 1035 | 1055 | +20 |
| fast-track | dispatch.py | `人工取消 hold-state（add-run-cancel D4，fast-track 同语义）` | 1922 | 1942 | +20 |
| repair | dispatch.py | `人工取消 hold-state（add-run-cancel D4，repair worker）` | 2402 | 2419 | +17 |
| planner-plan | verification.py | `人工取消 hold-state（add-run-cancel D4）` | 1618 | 1629 | +11 |
| planner-judge | verification.py | `人工取消 hold-state（add-run-cancel D4，judge 同语义）` | 1993 | 2003 | +10 |
| legacy-verifier | verification.py | `人工取消 hold-state（add-run-cancel D4，legacy verifier）` | 2826 | 2836 | +10 |

「恰好命中 1 次」是硬约束：定位函数在未命中（0 次）或多命中（>1 次）时都会抛红，因此锚点串一旦因注释改写而失效/复重，测试会自行暴露并提示精确定位，无需手工行号对齐。

### D2: 定位函数对锚点串做唯一性断言

```python
def _locate(rel, anchor, label):
    lines = _load(rel)
    hits = [i for i, ln in enumerate(lines, 1) if anchor in ln]
    if not hits:
        raise AssertionError(f"{rel} ({label}) 锚点串未命中：{anchor!r}（注释被改写/删除？）")
    if len(hits) > 1:
        raise AssertionError(f"{rel} ({label}) 锚点串命中 {len(hits)} 次：{anchor!r}（不唯一，请改用更精确串）")
    return hits[0]
```

唯一性自证**内化到定位函数本身**，不再依赖人肉核对行号。

### D3: 断言窗口改为「锚点行 + 相对偏移窗口」

`WRITE_POINTS` 由 `(rel, line_no, label)` 改为 `(rel, anchor, label)`；`test_six_holdstate_write_points_carry_marker` 取锚点行起 `[anchor_line, anchor_line + 25)` 窗口，断言窗口内同时出现 `"_cancelled_hold": True` 与 `"error": cancelled_err`。+25 覆盖表内最大偏移 +20 并留余量；若未来某处写点与锚点距离拉大越过窗口，报错信息会提示窗口大小，按表内偏移调整即可。

### D4: 双重对账——锚点表与全库扫描平行

保留 `test_no_new_holdstate_write_point_missed` 的全库扫描（`"hold-state"` + `"人工取消"` 断言恰好六处命中文件），与六条锚点表**并行**：表内条目数 = 全库扫描命中的写点文件集合数，互为印证。未来新增 run 类型时，两个校验会同时红。

### D5: 清除行号考古注释

删除 `WRITE_POINTS` 块内三次重钉留下的绝对行号溯源注释（981/1005/1055 等历史行号与 `14380774`/`2e98e052`/`762b4aee` 考古），代之以 D1 的锚点串表 + 每条一句语义说明。

### 备选方案（已排除）

- **函数名锚定（`def` 行 + 相对偏移）**：`verification.py` 的 planner-plan 与 planner-judge 同在 `_run_three_stage_verification` 内，函数名无法区分二者，仍需函数内阶段日志，相当于退回 D1。排除。
- **全文件定位 `"_cancelled_hold": True` 所有命中再按顺序映射 label**：顺序耦合同样脆弱，且丢失每处写点语义的独立校验（一处错位会连带后续全部错位）。排除。

## Risks / Trade-offs

- [implementer 与 planner-plan 复用同一锚点串字面，且靠中文标点 `D4）` vs `D4，` 与 fast-track/repair 区分] → 定位函数唯一性校验会在串不唯一/漂移时立即红并打印精确串，风险自愈；且 implementer/file 维度已隔离，跨文件无冲突。
- [锚点注释未来被重写或删除（重构时清理注释是常态）] → 未命中/多命中红测试 + 报错含 label 与锚点串，定位即诊断，改锚点串是语义明确的单点更新。
- [窗口 +25 行是硬编码，写点与锚点距离若被大幅插行拉大] → 报错提示窗口边界，实现时按表内偏移字段可参数化窗口宽度，避免再次手工考古。

## Migration Plan

无运行时迁移。仅测试文件改动；改动后全量跑 `tests/test_cancel_holdstate_recovery.py` 应全绿（含当前已红灯的 3 个 subtest 恢复绿）。回滚即还原该测试文件的一个 commit。