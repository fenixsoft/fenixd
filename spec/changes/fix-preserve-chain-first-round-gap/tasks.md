## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: tests/test_interrupt_recovery_preserve.py
  kind: modify
```

## 1. spec → worktree/branch 事实查询

- [ ] 1.1 在 `core/worktree_manager.py` 新增 spec → worktree/branch 查询：以 `git worktree list --porcelain` 取在册 worktree 全集，按 worktree 目录命名约定（`impl-<spec>-<ts>`）以**完整 spec 名 + 分隔符边界**匹配（禁止子串包含），返回 `(wt_path, branch)`；歧义命中（多个匹配）MUST NOT 静默取首个，返回 None 并 WARNING。
- [ ] 1.2 查询结果 MUST 经既有 `is_available`（`core/worktree_manager.py:2956`）三态单源校验：非 available/rebuildable 的候选不得作为保全与保留依据；MUST NOT 读取 `_active_worktrees` / `_wt_branches` 内存表作为判据（daemon 重启即失）。
- [ ] 1.3 查询 MUST 有超时与异常降级（git 命令失败返回 None 并 WARNING），MUST NOT 阻塞停机路径。

## 2. 保全链回落（STATE branch 缺失不再等于放弃）

- [ ] 2.1 `fenixd.py` `_preserve_interrupted_runs`（`:1092-1155`）：`entry.get("branch")` 为空时回落 1.1 查询取 branch 与 worktree；保护集 `seen_wt` MUST 以解析结果补入。
- [ ] 2.2 `core/state_machine.py` `_recovery_preserve_spec`（`:868-930`）：`if not branch: return False` 之前 MUST 先尝试 1.1 查询；查询得到有提交分支时走保留续做路径，MUST NOT 落入清空分支（`:854-865`）。
- [ ] 2.3 `cleanup_orphans` 保护集构造（`fenixd.py:1314` 调用侧）：sidecar 条目 worktree 为空串时，MUST 以该 spec 的查询结果补入 `protected`，MUST NOT 放行清理。
- [ ] 2.4 回归红线：非计划 SIGTERM（restart_request 不在册）快速停机路径 MUST 逐字节不变；零提交分支 MUST 仍走现行清空重建。

## 3. 删除前置留档

- [ ] 3.1 `core/worktree_manager.py` `cleanup_orphans`（`:725`）：物理删除前 MUST 对目标 worktree 调用 `_snapshot_dirty_worktree` 并日志留痕；失败降级 WARNING 不阻塞删除。
- [ ] 3.2 `core/worktree_manager.py` `cleanup`（`:554`）：快照 MUST 从「`git worktree remove` 失败的 rmtree 兜底分支（`:622`→`:638`）」上提为删除前置动作，使 `--force` 成功路径同样留档，MUST NOT 因命令返回 0 而跳过。
- [ ] 3.3 确认无重复留档：同一 worktree 在同一次清理中 MUST NOT 因路径重叠产生两次快照写入（幂等或前置短路）。

## 4. 回归测试

- [ ] 4.1 `tests/test_interrupt_recovery_preserve.py`：新增「首轮在飞 run（STATE branch=None、worktree 在册）被排水强杀」用例，断言 sidecar 条目的 branch 与 worktree 均非空串。
- [ ] 4.2 新增「STATE branch 为空但在册 worktree 分支有提交」的 recovery 用例，断言判定为保留续做且不调用清空路径。
- [ ] 4.3 新增「sidecar worktree 为空串但在册 worktree 存在」用例，断言该 worktree 进入保护集并跳过 orphan 清理。
- [ ] 4.4 新增「orphan 清理与 `--force` 成功路径均在删除前留档」用例，断言快照调用发生在删除之前（可用 mock 断言调用顺序）。
- [ ] 4.5 新增命名歧义用例：spec 名互为前缀时查询返回 None 而非误匹配。
- [ ] 4.6 既有用例全绿：非计划 SIGTERM 零变化、零提交分支清空重建两条红线用例 MUST 保持通过。

## 5. 端到端验证

- [ ] 5.1 构造本地时序复现：起一个 implementing run 抢占分支 → 在 branch 未写 STATE 的窗口触发排水超时 terminate → 断言 sidecar 含 branch/worktree 且 worktree 未被 orphan 清理删除。
- [ ] 5.2 重启后恢复验证：断言该 spec 走 resume 续做（继承注记 + `claude --resume`），MUST NOT 从零重派新分支。
