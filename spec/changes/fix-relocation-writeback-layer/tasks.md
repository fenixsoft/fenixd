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
> `core/deliverables.py` 的 `_has_relocation_credential`（布尔判定，不返回替代路径）
> 为既有函数，本轮另需在 `core/deliverables.py` 新增一个**返回替代路径**的查询辅助
> （见 4.1），供守卫核销前校验「替代路径在分支 HEAD 存在」。

## 1. 写回层解析与提交根

- [ ] 1.1 在 `core/deliverables.py` 新增写回层判定辅助（如 `resolve_writeback_target(spec_name, *, branch, worktree_path, project_root) -> dict`）：调用既有 `resolve_effective_declaration`，返回 `{"writable": bool, "spec_dir": str|None, "source": str}`。判据 = **写入层是否等于守卫实际读到的那一层**（同源原则）：
  - `source == "worktree"` → `writable=True`，落点 = `spec_dir`（worktree 内 spec 目录），提交根 = 该 worktree；
  - `source == "main"` → `writable=True`，落点 = `spec_dir`（**主树** spec 目录，提交根 = `project_root`）——此时守卫读取基准**就是主树**（`resolve_effective_declaration` 优先序 worktree > branch > main 中前两层均未命中），就地写入即同源，不构成错层；反向禁止会误伤既有可用路径（`_preclassify_missing` / reference 软化的主树就地软化 + 立即提交路径，见 `tests/test_deliverable_declaration_triage.py::TestSoftenedDeclarationIsCommitted` 与 2026-09-15 merge-back 死锁修复）；
  - `source == "branch"`（`spec_dir is None`，声明只存在于分支对象库、无落盘位置）→ `writable=False`：**这才是事故态**（写主树、守卫读分支），MUST NOT 以主树 `tasks.md` 为落点假装修正已生效；
  - `source is None`（两处均不可用）→ `writable=False`。
- [ ] 1.2 `core/pm_engine/engine.py::_git_commit` 增可选提交根参数（如 `repo_root=None`，缺省 `project_root` 保持既有行为），透传到 `git add`/`git commit` 的 `cwd`；核对既有调用点（软化/删除等）以缺省值调用不回归
- [ ] 1.3 `core/pm_engine/dispatch/adjudication.py::_commit_softened_declaration` 增可选提交根参数（worktree 路径）并在调用点传入，使软化/typo 修正可提交到 worktree 分支
- [ ] 1.4 worktree 被占用的降级路径（design「Risks」第 2 条）：写回层为 worktree 且写入/提交失败（worktree 被实现 run 占用、`git add/commit` 冲突或异常）时，MUST 降级为打回/凭据通道，MUST NOT 改落主树「兜底」、MUST NOT 静默判修正成功

## 2. judge 修正落点对齐（typo / reference / delete）

- [ ] 2.1 `_adjudicate_deliverable_missing` 的 `typo` 分支（非陈日路径，`adjudication.py` 现 `replace_declared_path(eff_spec_dir, …)` 点，**即事故点**：`eff_spec_dir` 现由 `spec_dir or 主树` 回退而来）改用 1.1 的写回层判定：`writable=True` 时以 `spec_dir`（其来源层）执行 `replace_declared_path` 并提交到该层（worktree 来源→该 worktree 分支；main 来源→`project_root`）；`writable=False`（`source == "branch"`，`spec_dir is None`）时 MUST NOT 调 `replace_declared_path`，转为打回/凭据通道，**且该条 typo 裁决（element + actual_path）MUST 仍落 dispute 审计流**（供 4.1 的核销在下一轮生效）
- [ ] 2.2 `reference` 软化**全部**调用点同样以 1.1 判定落点：`adjudication.py::_adjudicate_deliverable_missing` 的 reference 分支与 `adjudication.py::_preclassify_missing` 的确定性软化点（现 `spec_dir or 主树` 回退处）——`writable=True` 就地软化并立即提交；`writable=False` 时 MUST NOT 软化主树，转打回，且该条 reference 裁决 MUST 落审计流（同 2.1 留册要求）
- [ ] 2.3 陈日重定位分支（`_relocate_or_register` 调用点）以 1.1 判定落点：`writable=False` 时跳过写主树、保持既有 `register_relocation_credential` 凭据登记后交打回，MUST NOT 以主树 `tasks.md` 为改写落点（该分支已按 `spec_dir is None` 判据分流，本轮仅需与 1.1 判据对齐去重）
- [ ] 2.4 `_preclassify_orphan` 的删除条目点（`adjudication.py` 现 `spec_dir or 主树` 回退 + `remove_declared_entry`）以 1.1 判定落点：`writable=False` 时不写主树、不留主树提交，回退既有 blocked 待人工/续走通道
- [ ] 2.5 全量清点 `tasks.md` 声明段的写入点（`grep -rn "replace_declared_path\|soften_declared_kind\|remove_declared_entry\|relocate_declared_path\|soften_unsatisfiable_declarations" core/`）并逐一接线 1.1 判据，写入清单落 `.history` 备查；清点覆盖 `adjudication.py` 的 `_preclassify_missing` / `_preclassify_orphan` / judge 执行三处与 `promotion.py` 晋升软化点（晋升期无实现分支，`source == "main"` → `writable=True`，行为不变）——任何未接线的写入点即为本 SPEC 留下同类错层

## 3. 修正后读取一致性复检熔断

- [ ] 3.1 新增复检函数（如 `core/deliverables.py::verify_correction_readback(spec_name, corrected_path, *, branch, worktree_path, project_root) -> bool`）：以 `resolve_effective_declaration` 复读，断言 `corrected_path`（旧路径）不再以原 kind 出现在 `deliverables` 中
- [ ] 3.2 `_adjudicate_deliverable_missing` 在 typo/reference 修正执行后调用 3.1：复检失败（读到仍是旧路径）时把 `source`/`spec_dir` 写入 error 明细并 `logger.warning`，MUST NOT 判修正成功
- [ ] 3.3 单元测试：构造「修正只落主树、分支/worktree 版本仍含旧路径」态，断言 3.1 返回 False 且处置侧产生告警（不静默）

## 4. 跨轮残留凭据核销（脱困）

- [ ] 4.1 在 `core/deliverables.py` 新增**返回替代路径**的凭据查询辅助（如 `relocation_credential_target(project_root, path) -> str | None`，与既有 `_has_relocation_credential` 同源读 `.fenix/dispute_audits.jsonl`，返回 `new_path` / `actual_path` 而非布尔）：`_has_relocation_credential` 现为纯布尔判定（`core/deliverables.py:767`），**不返回替代路径**，守卫无法据其完成「替代路径在分支 HEAD 存在」的核销前校验
- [ ] 4.2 `core/pm_engine/verification/branch_guard.py::_deliverable_gate_missing` 产出 `violations` 后：**仅对 `violation == "missing"` 的条目**做核销判定（`undeleted` / `removed` MUST NOT 被本条吞掉，其豁免仍走既有 `check_declaration_shrinkage` 通道）——命中凭据且 `4.1` 返回的替代路径在**分支 HEAD 存在**（`worktree_manager.file_exists_on_branch`）→ 视为已核销，不加入 `violations`；替代路径为空或不存在时 MUST NOT 核销（防空洞核销），走既有缺件处置
- [ ] 4.3 核销发生时 `logger.info` 留痕（spec、旧路径、替代路径、来源=dispute 凭据），不静默
- [ ] 4.4 单元测试：伪造 `.fenix/dispute_audits.jsonl` 含 `typo` 凭据（替代路径在分支存在）→ 断言守卫不再报该 `missing`；替代路径不存在 → 断言仍报 `missing`；`kind: delete` 的 `undeleted` 条目即使有凭据也不被核销（守 `missing` 作用域）

## 5. 复发熔断（迁移期安全网）

- [ ] 5.1 复发计数 MUST 用**独立字段**（如 `_writeback_recur_streak` + `_writeback_recur_path`，落 STATE.md spec entry），**MUST NOT 复用 `_retry_count`**：该字段在恢复续做/阻塞复位路径被清零（`state_machine.py:1729` 恢复续做 `_recovery_resume` 分支、`:1469` 重建分支均写 `"_retry_count": 0`），而 `resolve_env_blocked_reset_path`（`branch_guard.py:23-53`）会把本类 loop 的 blocked 复位为 ready 续走重实现——事故态实证：31 小时在飞期间 `.fenix/STATE.md` 的 `_retry_count` 为 `0`，既有封顶（`adjudication.py:1675-1681`）从未生效。独立字段 MUST NOT 随 blocked→ready / 恢复续做清零（仅在 typo 修正复检通过或 SPEC 退出本形态时清零）
- [ ] 5.2 达 `agents.max_retries` 上限（或专用阈值，取其一并在实现中写明）→ 置 `blocked`，error 文案区分「修正未生效于读取基准」形态（相对既有「缺件」文案），不再自动重派
- [ ] 5.3 单元测试：连续 N 轮同路径复发（含中间穿插 blocked→ready 复位）→ 断言独立计数不被复位清零、第 N 轮置 blocked；typo 修正复检通过 → 断言计数清零

## 6. 端到端回归与预演

- [ ] 6.1 `tests/test_relocation_writeback_layer.py` 覆盖各态：有 worktree → 修正写 worktree 并提交该分支；`source == "main"` → 就地写主树并提交（同源，不得被判错层）；`source == "branch"` → 不写主树（走打回 + 裁决落册）；复检不一致告警；残留凭据核销；worktree 写入冲突降级
- [ ] 6.2 回归 `tests/test_deliverable_*` / `tests/test_declaration_*` 相关套件全绿（含 `add-declaration-relocation-protocol` 既有 Scenario 不回归）。重点核对「改写落点」断言族：(a) `tests/test_deliverable_declaration_triage.py::TestSoftenedDeclarationIsCommitted`（`tests/test_deliverable_declaration_triage.py:912-967`，fixture 无真实 worktree、`git show` 不命中 → 解析为 `source == "main"`）——1.1 的 main 来源 `writable=True` 与既有的「主树就地软化 + 立即提交」语义一致，MUST 继续通过（该断言背后是 2026-09-15 merge-back 死锁修复，不得回归）；(b) 若存在以「`source == "branch"`（`spec_dir=None`）仍改写主树并提交」为断言的测试，即属旧错层语义，MUST 改为「不写主树 + 走打回/凭据」，并在勾选本任务前完成更新
- [ ] 6.3 `_preclassify_missing` / `_preclassify_orphan` 既有单测（`tests/test_deliverable_declaration_premechanize.py`、`tests/test_deliverable_orphan_preclassify.py`）回归全绿（其 fixture 同为 `source == "main"`，按 1.1 落点不变）
- [ ] 6.4 装配复现预演：以「声明的 typo 路径 + 分支携带旧声明（`source == "branch"`）+ 主树已修正」构造夹具，跑守卫对账，断言新逻辑下缺件被凭据核销（复现事故态并验证脱困）；再以 `source == "main"` 夹具断言就地写入 + 复检通过（不误判为错层）
