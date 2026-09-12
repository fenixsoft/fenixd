## Deliverables

```yaml
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_fast_track_dispatch.py
  kind: modify
- path: tests/test_pm_verification.py
  kind: modify
```

## 1. 分支提交判定 helper（design D1）

- [ ] 1.1 在 `core/pm_engine/verification.py` 新增 `_implementation_branch_has_commits(result)`：`git rev-list --count main..<branch>` > 0 判定，`result.branch` 为空或 rev-list 失败/超时一律返回 False（conservative fail-open，见 design D1）
- [ ] 1.2 重构 `_implementer_zero_change` 复用该 helper 取代内联 rev-list 判定，保证行为不变
- [ ] 1.3 单测覆盖 helper 四态：分支有提交 / 分支零提交 / `result.branch` 为空 / rev-list 失败（均走 False 或正确 True）

## 2. fast-track 死亡路径分流（design D2）

- [ ] 2.1 在 `_run_fast_track_flow` 的 `ft_result is None` 分支（`core/pm_engine/dispatch.py` 约 1944-1954）先跑 1.1 helper 分流，不改变 `ft_result` 存在时的既有流程
- [ ] 2.2 有提交分支：调用 `_reconcile_and_merge(spec_name, result)` 合并；合并成功后改写 `.spec.yaml` mode→full 并 `_enqueue(spec_name, "verifier")`（复用/抽取 `_escalate_to_full_mode` 的 mode-改写 + enqueue 语义，触发因写「结果文件缺失，分支已提交，升级补验证」）；合并失败沿用 `_reconcile_and_merge` 既有处置（保留 worktree + 重派/熔断）
- [ ] 2.3 零提交或无 `result.branch` 分支：维持原 `_handle_fast_track_failure` 调用，绝不改死亡豁免 + reset ready + 自动重派语义
- [ ] 2.4 单测：fast-track 分支有提交但结果文件缺失 → 不豁免预算、不 reset ready，分支被 merge 且 enqueue verifier（`tests/test_fast_track_dispatch.py`）
- [ ] 2.5 单测：fast-track 分支零提交（或无 branch）结果文件缺失 → 维持死亡豁免 + reset ready + 重派（不回归）

## 3. 共享结果文件 stamp 收紧与清理（design D3/D4）

- [ ] 3.1 `_read_implementer_result`（`core/pm_engine/engine.py` 约 753-765）stamp 守卫收紧为 fail-closed：`spec` 字段非严格等于当前 spec（含 None/空/非字符串）即 ignore 返回 None；worktree 文件同规则收紧
- [ ] 3.2 消费后清理：fast-track 与 implementer 成功收口在 `_write_impl_result_snapshot` 落盘 per-spec 快照**之后**删除主树共享 `.fenix/.fenix-run-result.json`；删除失败仅记 WARNING 不阻塞（fail-open）
- [ ] 3.3 单测：主树共享文件 stamp 不符 / 无 stamp（缺失/空/非字符串）/ 严格匹配 三态采信行为（不符与无 stamp 均返回 None）
- [ ] 3.4 单测：消费并落盘快照后删除共享文件；删除失败（OSError）仅记日志不阻塞

## 4. 回归与实证验收

- [ ] 4.1 全量回归受影响的既有测试（`test_fast_track_dispatch.py` / `test_pm_verification.py` / `test_pm_dispatch.py` / `test_agent_runner_gate.py`）全绿，无既有语义回归
- [ ] 4.2 用日志夹具回放验证判定：构造「分支有提交但结果文件缺失」夹具，确认走 merge+升级补验证而非 death 豁免（对齐本变更 proposal 的两起事故签名）