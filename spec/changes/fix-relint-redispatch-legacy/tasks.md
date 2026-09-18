# Tasks: fix-relint-redispatch-legacy

## Deliverables

```yaml
- path: core/pm_engine/dispatch.py
  kind: modify
- path: tests/test_tasksmd_relint_gate.py
  kind: modify
- path: tests/test_redispatch_artifact_succession.py
  kind: new
```

## 1. 阶段 1：登记分支遗产

- [x] 1.1 `_redispatch_tasks_relint` 签名扩展：新增可选参数 `branch: str | None = None`（保持 `agent_type` / `run_id` 既有默认值不变，既有调用与测试零改动）
- [x] 1.2 登记逻辑：在状态写回与 `_enqueue_front` **之前**插入仅分支模式登记——`if branch and hasattr(wm, "register_legacy"): wm.register_legacy(spec_name, None, branch)`（`wm = self._pm.agent_runner.worktree_manager`）；分支为空则跳过；登记异常捕获降级 WARNING（fail-open，不阻断处置）
- [x] 1.3 调用点传参：full 车道 relint 分支处补 `branch=getattr(result, "branch", None)`（该分支已持有 `result`，用于 `_tasks_md_relint_from_branch`）
- [x] 1.4 登记顺序核对（design D3）：确认与 `fix-redispatch-loop-governance` 的 worktree 保留机制在 `_legacy` 覆盖式更新下不互相清除现场——若两者可能同时命中同一轮，MUST 保证含路径的 worktree 模式遗产优先（实现时以 `worktree_manager` 的实际语义核对并记入代码注释）

## 2. 阶段 2：测试

- [x] 2.1 `tests/test_tasksmd_relint_gate.py` 补用例：relint 违规触发 `_redispatch_tasks_relint` 且传入 branch 时，`worktree_manager` 的遗产在册（`_legacy` 含该 spec 且 `reuse` 为真）
- [x] 2.2 补用例：传入 `branch=None` 时安全跳过登记且重派照常（`status=ready` + `_retry_count` 递增 + 已入队）
- [x] 2.3 新增 `tests/test_redispatch_artifact_succession.py`：以「遗产在册 + `_take_reusable_worktree` 可认领」为判据，逐条断言适用打回路径（交付物守卫缺件打回、relint 违规打回）登记了分支遗产——**不**断言「调用了某函数」，使实现重构不破坏断言语义
- [x] 2.4 继承链端到端断言：relint 打回后，下一次 `worktree_manager.create(spec, "implementer")` 认领同一分支（MUST NOT 新建 worktree、MUST NOT 从 main 起新分支）
- [x] 2.5 fast-track 车道不受影响断言：其 relint 处置仍走 `_keep_fast_track_worktree`，不因本变更改变行为

## 3. 阶段 3：回归与收尾

- [x] 3.1 运行 `bin/run_full_suite.py` 与基线比对，确认不新增失败（重点 `test_tasksmd_relint_gate` / `test_deliverable_gate` / `test_recovery_legacy`）
- [x] 3.2 patch 缝隙专项：确认 `dispatch.py` 的既有模块级 patch 语义（`time`）未被破坏
- [x] 3.3 逐项勾选本 tasks.md 全部已完成任务
