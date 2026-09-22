# Tasks: fix-relocation-writeback-layer

## Deliverables

```yaml
- path: core/pm_engine/dispatch/adjudication.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/verification/branch_guard.py
  kind: modify
- path: tests/test_relocation_writeback_layer.py
  kind: new
```

> 说明：`.fenix/dispute_audits.jsonl` 为运行时文件（gitignored），仅读取，不列为交付物；
> `core/deliverables.py` 的 `_has_relocation_credential` 为既有函数，本轮在守卫侧接线消费。

## 1. 写回层解析与提交根

- [ ] 1.1 在 `core/deliverables.py` 新增写回层判定辅助（如 `resolve_writeback_target(spec_name, *, branch, worktree_path, project_root) -> dict`）：调用既有 `resolve_effective_declaration`，返回 `{"writable": bool, "spec_dir": str|None, "source": str}`——仅当 `source == "worktree"` 且 `spec_dir` 位于 worktree 内时 `writable=True`；`branch`/`main` 来源一律 `writable=False`（MUST NOT 以主树为落点）
- [ ] 1.2 `core/pm_engine/engine.py::_git_commit` 增可选提交根参数（如 `repo_root=None`，缺省 `project_root` 保持既有行为），透传到 `git add`/`git commit` 的 `cwd`；核对既有调用点（软化/删除等）以缺省值调用不回归
- [ ] 1.3 `core/pm_engine/dispatch/adjudication.py::_commit_softened_declaration` 增可选提交根参数（worktree 路径）并在调用点传入，使软化/typo 修正可提交到 worktree 分支

## 2. judge 修正落点对齐（typo / reference / delete）

- [ ] 2.1 `_adjudicate_deliverable_missing` 的 `typo` 分支（非陈日路径）改用 1.1 的写回层判定：`writable=True` 时以 worktree 内 `spec_dir` 执行 `replace_declared_path` 并提交到该 worktree 分支；`writable=False` 时 MUST NOT 调 `replace_declared_path` 写主树，转为走缺件打回/凭据通道
- [ ] 2.2 `reference` 软化分支（`soften_declared_kind`）同样以 1.1 判定落点：仅 `writable=True` 就地软化提交；否则转打回/凭据通道
- [ ] 2.3 陈日重定位分支（`_relocate_or_register` 调用点）以 1.1 判定落点：`writable=False` 时跳过写主树，走凭据登记（`register_relocation_credential`）后交打回，MUST NOT 以主树 `tasks.md` 为改写落点
- [ ] 2.4 删除条目分支（`remove_declared_entry`）以 1.1 判定落点，`writable=False` 时不写主树

## 3. 修正后读取一致性复检熔断

- [ ] 3.1 新增复检函数（如 `core/deliverables.py::verify_correction_readback(spec_name, corrected_path, *, branch, worktree_path, project_root) -> bool`）：以 `resolve_effective_declaration` 复读，断言 `corrected_path`（旧路径）不再以原 kind 出现在 `deliverables` 中
- [ ] 3.2 `_adjudicate_deliverable_missing` 在 typo/reference 修正执行后调用 3.1：复检失败（读到仍是旧路径）时把 `source`/`spec_dir` 写入 error 明细并 `logger.warning`，MUST NOT 判修正成功
- [ ] 3.3 单元测试：构造「修正只落主树、分支/worktree 版本仍含旧路径」态，断言 3.1 返回 False 且处置侧产生告警（不静默）

## 4. 跨轮残留凭据核销（脱困）

- [ ] 4.1 `core/pm_engine/verification/branch_guard.py::_deliverable_gate_missing` 在产出 `missing` 后：对每条命中 `_has_relocation_credential` 且其替代路径在分支 HEAD 存在的条目，视为已核销（不加入 `violations`）；替代路径不存在时不核销（防空洞核销）
- [ ] 4.2 核销发生时 `logger.info` 留痕（spec、旧路径、来源=dispute 凭据），不静默
- [ ] 4.3 单元测试：伪造 `.fenix/dispute_audits.jsonl` 含 `typo` 凭据（替代路径在分支存在）→ 断言守卫不再报该 `missing`；替代路径不存在 → 断言仍报 `missing`

## 5. 复发熔断（迁移期安全网）

- [ ] 5.1 `_redispatch_for_missing` 对「同路径在 typo 修正后连续复发」计入既有 `_retry_count`；达 `agents.max_retries` 上限置 `blocked`，error 文案区分「修正未生效于读取基准」形态（相对既有「缺件」文案）

## 6. 端到端回归与预演

- [ ] 6.1 `tests/test_relocation_writeback_layer.py` 覆盖四态：有 worktree 修正写 worktree；无 worktree 不写主树（走打回）；复检不一致告警；残留凭据核销
- [ ] 6.2 回归 `tests/test_deliverable_*` / `tests/test_declaration_*` 相关套件全绿（含 `add-declaration-relocation-protocol` 既有 Scenario 不回归）
- [ ] 6.3 装配复现预演：以「声明的 typo 路径 + 分支携带旧声明 + 主树已修正」构造夹具，跑守卫对账，断言新逻辑下缺件被核销（复现事故态并验证脱困）
