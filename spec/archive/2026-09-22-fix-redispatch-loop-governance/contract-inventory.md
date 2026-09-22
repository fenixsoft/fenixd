# Contract Inventory — fix-redispatch-loop-governance

契约清单：诚实退出收敛（honest-exit-convergence）与重派循环治理
（redispatch-loop-governance）的机械事实登记。本文件是契约测试的期望序列来源，
**任何一项变更都必须同步更新本清单与对应测试**，否则视为契约漂移。

## 1. 缺口推导位置静态清点（tasks 1.1）

全仓「推导 partial 缺口」的位置逐项核查：只读结果文件，或回退读主树
`tasks.md` 勾选（禁止项）。

### 1.1 结论总表

| 位置 | 函数 | 缺口来源 | 是否读主树勾选 | 判定 |
|---|---|---|---|---|
| `core/run_task_track.py:139` | `gap_from_result` | 结果文件 `unfinished` 优先；否则 `completed_tasks` 反推（`全部任务 id − completed_tasks`） | 仅取任务 **id 清单**（`parse_tasks_md` 第一返回值），**不消费勾选状态** | ✅ 单一实现点 |
| `core/pm_engine/dispatch/rollback.py:24` | `_honest_exit_gap` | 调 `gap_from_result` | 否 | ✅ |
| `core/pm_engine/engine.py:846` | `_partial_attribution` | `unfinished` 优先；缺失时调 `gap_from_result` | 否 | ✅ |
| `core/pm_engine/engine.py:1191` | `_task_completion_blocker`（partial 分支） | 调 `gap_from_result` | 否 | ✅ |

**无一处**在缺 `unfinished` 时回退读主树 `tasks.md` 勾选状态——2026-09-17
读侧自锁事故（主树 `[x]` 只在成功/merge-back 路径由 `_sync_task_progress` 回写，
partial 收敛走不到，读它会把已完成任务算成缺口）的消解即此。

### 1.2 其余消费主树勾选的位置（非 partial 缺口推导，逐项注明语义合法）

| 位置 | 函数 | 消费主树勾选的方式 | 为何合法 |
|---|---|---|---|
| `core/agent_runner/result_gate.py:460` | `_check_impl_result_artifact` | 以 **worktree** 内 `tasks.md` 为对象解析勾选 | 产物硬门的校验基准是本轮 run 的 worktree 内成果（`wt_path / spec/.../tasks.md`），不是主树；受理态是「本轮产物」，与 partial 收敛路径正交 |
| `core/pm_engine/engine.py:1183` | `_task_completion_blocker`（证据缺失兜底分支） | `parse_tasks_md` 判「有无未勾数字任务」作 fail-closed 拦截依据 | 仅当 `.fenix-run-result.json` 证据全缺（快照与共享文件均无）时触发，归因文案为「run 证据缺失…需人工确认」；属 fail-closed 兜底而非收敛判据 |
| `core/pm_engine/engine.py:1228` | `_task_completion_blocker`（success 分支） | 主树勾选 + run `done_ids` 求缺口 | verified→done 门禁的成功路径判据；success 必经 merge-back，`_sync_task_progress` 已回写主树，读主树勾选语义正确 |
| `core/run_task_track.py:109` | `parse_tasks_md` 自身 | — | 中性解析器，产出 `(all_ids, checked_ids)`；消费方决定取哪一半 |

### 1.3 无归属项

`grep -rn "parse_tasks_md\|gap_from_result" core/` 全量命中已在上表逐项归属，
**无未归属项**。

## 2. 收敛链固化（tasks 1.2）

两处 `honest_exit_gap` 调用点的逐行记录——收敛成立后 `is_success` /
`final_error` 如何改写、后续走哪条分支（契约测试的期望序列来源）。

### 2.1 full 车道：`core/pm_engine/dispatch/queue.py` `_run_agent_worker`

实现者分支内（agent_type == "implementer"，queue.py:552 起）：

```
1. run_implementer → _read_implementer_result → impl_result / impl_status / impl_error
   - impl_status == "partial" → impl_error = _partial_attribution(...)  （D6 归因）
2. is_success = result.success and (impl_status is None or impl_status == "success")
3. 诚实退出收敛判定（queue.py:666-689）：
   if impl_status == "partial":
       honest_exit_gap = _honest_exit_gap(pm, spec_name, impl_result)
   if result.success and impl_status == "partial" and honest_exit_gap:
       │  ── 收敛成立 ──
       │  impl_error = None            （覆盖 D6 归因）
       │  is_success = True            （覆盖 is_success 假值）
       │  _note_unattainable_todos(spec_name, impl_result, honest_exit_gap)（人工待办告警）
       │  日志 warning：诚实退出收敛…不重派，按成功收口转验证
4. final_error = impl_error or result.error
5. is_success=True → 顺序过门（不短路）：
   ├─ 零变更哨 _implementer_zero_change（确认型 no-op 放行需交付物齐备 + 分支并入 main）
   ├─ 交付物守卫 _deliverable_gate_missing（缺件 → dispute 裁决 / missing 补做重派）
   ├─ tasks.md relint _tasks_md_relint_from_branch（违规 → _redispatch_tasks_relint）
   ├─ impl-result per-spec 快照 _write_impl_result_snapshot + 共享结果文件清理
   ├─ 锚点提前落盘（branch / implementer_run → STATE）
   ├─ merge_back_from_branch（失败 → 指纹熔断 _merge_fp/_merge_streak / repair / 重试）
   └─ transition(implemented) + update_spec(_retry_count=0) + _enqueue_front(verifier)
6. 若 is_success=False → else 分支：取消 hold / 死亡豁免 / provider 熔断 /
   provider-transient 排程 / 通用失败重派（_retry_count 递增，max_r 封顶）
   —— 本 SPEC 阶段 3 在此分支接入同因重派熔断。
```

**收敛成立的改写要点**：`impl_error=None` 与 `is_success=True` 是收敛分支的显式
原子改写（queue.py:680-681），不得移除；收敛后走**既有成功路径全链**，
MUST NOT 短路任何一道门（spec「收敛后不因缺口跳过门」）。

### 2.2 fast-track 车道：`core/pm_engine/dispatch/fast_track.py` `_run_fast_track_flow`

fast-track worker（fast_track.py:147 起）：

```
1. result.cancelled → hold-state（早退）
2. _read_implementer_result → ft_result
   - ft_result is None → 结果文件缺失分流（分支已提交 → merge + 升级完整模式；
     分支零提交 → 死亡豁免 + reset ready + 重派）
3. 诚实退出收敛判定（fast_track.py:208-254）：
   if result.success and ft_result.get("status") == "partial":
       honest_exit_gap = _honest_exit_gap(pm, spec_name, ft_result)
   if not result.success or (status != "success" and not honest_exit_gap):
       │  失败通道：_keep_fast_track_worktree + _handle_fast_track_failure（重派）
   if honest_exit_gap:
       │  ── 收敛成立（注释语义：继续走零变更哨/守卫/relint/merge/verified 推进）──
       │  _note_unattainable_todos（人工待办告警，与 full 车道同文案）
       │  日志 warning：诚实退出收敛（fast-track）…
4. 零变更哨 → 交付物守卫 → relint（三道门与 full 车道同语义）
5. _hard_check_fast_track（本 SPEC D2a 修复点前：要求合法 verification 段）
6. 校验通过 → _reconcile_and_merge（merge + transition(implemented)）
   → impl-result 快照 + 共享结果文件清理
   → verdict == bug-found → _escalate_to_full_mode
   → 否则 _fast_track_advance_to_verified（verified 推进）
```

**D2a 修复前的事实**：`partial` + `unattainable` 的结果文件几乎必然不含合法
`verification` 段（`parse_fast_track_verification` 要求 scenarios 非空且
verdict ∈ {verified, bug-found}）→ `_hard_check_fast_track` fail-closed →
`_keep_fast_track_worktree` + 重派 → **fast-track 车道诚实退出收敛实质是死路**
（注释「继续走零变更哨/守卫/relint/merge/verified 推进」与实际不符）。
本 SPEC 2.4 按 design D2a 方案 (a) 修复：识别收敛形态后跳过 verification 段要求，
**降级完整模式补独立验证**。

## 3. 两车道对称性（tasks 2.1）

### 3.1 三项逐项比对（修复后）

| 维度 | full 车道 | fast-track 车道 | 比对 |
|---|---|---|---|
| 判据函数 | `Dispatcher._honest_exit_gap`（经 `runner_worker` 调用） | `Dispatcher._honest_exit_gap`（同名同函数） | ✅ 同一判据（单点 `core.run_task_track`） |
| 收口语义 | 不重派 + `impl_error=None`/`is_success=True` → 成功收口 | 不重派 + 跳过 `_hard_check_fast_track` → merge + 降级完整模式（D2a 修复后） | ✅ 同语义（不重派 + 转成功收口） |
| 留痕 | `_note_unattainable_todos` + 日志 warning（含缺口清单） | `_note_unattainable_todos` + 日志 warning（含缺口清单） | ✅ 同形态（signal_type `impl_unattainable_tasks`） |

### 3.2 已知且允许的差异（design「允许差异」表，契约测试显式锁定）

| 维度 | full 车道 | fast-track 车道 |
|---|---|---|
| 收敛后去向 | `implemented` → 入队 verifier（独立验证车道） | `_reconcile_and_merge` → `implemented` + `.spec.yaml` mode→full + 入队完整模式 verifier（D2a 修复后；单 run 不再自证，补三阶段独立验证） |
| 缺口归因入口 | `_partial_attribution`（归因文案） | `_partial_attribution`（同函数，经 `_handle_fast_track_failure` 失败通道） |
| 失败通道收尾 | 通用失败重派分支（`_retry_count` 递增 / max_r 封顶 / 同因熔断） | `_handle_fast_track_failure`（`_retry_count` 递增 / max_r 封顶） |

## 4. 重派成果继承事实（tasks 4.1）

`keep_for_reuse` / `cleanup(success=True)` 触发点与位置关系（`core/agent_runner/runner.py`）：

| 触发点 | 条件 | 动作 |
|---|---|---|
| `runner.py:2533`（attempt 顶部取消） | fast-track 取消 | `keep_for_reuse`（保留目录+分支） |
| `runner.py:2622-2629` `_finalize_success` | implementer 成功 | `cleanup(wt_path, success=True)`——**先于返回**；成功路径 `worktree_path=None`（runner.py:2664），dispatch 层拿到结果时现场已被清理 |
| `runner.py:2664` | fast-track/repair 成功 | 不清理（`handed_off`），`worktree_path` 保留，由 dispatch 层处置 |
| `runner.py:2719/2733`（`_finalize_failure_keep`） | 失败/取消/transient | `keep_for_reuse` |

**确认事实**：`cleanup(success=True)` 在 `_finalize_success` 内、返回
`AgentRunResult(success=True)` **之前**执行（runner.py:2626-2629 → 2658）。
故成果继承的 keep 判定 MUST 落在该 cleanup 之前（design D4 方案 ①），
dispatch 层已无现场可保。