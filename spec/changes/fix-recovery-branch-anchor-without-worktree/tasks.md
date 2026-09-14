## Deliverables

```yaml
# ── 锚点落盘（D1/A）与待合并标记（D3/C）、顺序修复 ──────────────
- path: core/pm_engine/dispatch.py
  kind: modify

# ── 锚点解析回落链（D2/B）、恢复期消费标记（D4）、留痕（E）────────
- path: core/state_machine.py
  kind: modify

# ── 分支命名空间枚举查询（D2/B）、stale 清扫删分支保护（D6）──────
- path: core/worktree_manager.py
  kind: modify

# ── 关闭期保护集与 sidecar 触发条件（D5）───────────────────────
- path: fenixd.py
  kind: modify

# ── 文档 ────────────────────────────────────────────────────
- path: docs/help/03-lifecycle.md
  kind: modify

# ── 测试 ────────────────────────────────────────────────────
- path: tests/test_recovery_branch_anchor.py
  kind: new
- path: tests/test_repair_remerge_pending.py
  kind: new
- path: tests/test_interrupt_recovery_preserve.py
  kind: modify
- path: tests/test_mergeback_repair_lane.py
  kind: modify
- path: tests/test_daemon_lifecycle_races.py
  kind: modify
- path: tests/test_pm_verification.py
  kind: modify
```

## 1. 实现产物成功即落锚点（D1/A）

- [ ] 1.1 `core/pm_engine/dispatch.py`：implementer run 返回终态 success 后、merge 预演与 merge-back 之前，`update_spec` 写入该 run 的 `branch` 与 `implementer_run`（含日志「锚点已提前落盘」）；run 未达终态成功时 MUST NOT 写
- [ ] 1.2 `core/pm_engine/dispatch.py`：repair run 返回终态 success 后、`merge_back_from_branch` 之前，同样先写该实现分支的 `branch`（复用 1.1 的写入点，不复制逻辑）
- [ ] 1.3 `core/pm_engine/dispatch.py`：确认既有「merge-back 成功后写 branch」的四处调用点（`2496`、`1045`、`2776`、`1354`）保留且取值与 1.1/1.2 一致，MUST NOT 出现两处写入不同分支名
- [ ] 1.4 `core/pm_engine/dispatch.py`：清理 `_run_repair_worker` 的写入顺序——`update_spec({branch, implementer_run, ...})` MUST 先于 `wm.cleanup(wt_path, success=True)` 执行

## 2. 锚点的 git 分支命名空间回落（D2/B）

- [ ] 2.1 `core/worktree_manager.py`：新增按 spec 枚举候选实现分支的查询（建议名 `find_branches_by_spec`），以 `git for-each-ref refs/heads/<prefix>/<spec>-*` 为事实源；前缀取配置 `worktree.implement_branch_prefix`（缺省 `fenix`），MUST NOT 硬编码
- [ ] 2.2 `core/worktree_manager.py`：候选排序实现——先取 `git merge-base --is-ancestor main <branch>` 成立者，其中取 committerdate 最新；无「已含 main」候选时取 `git rev-list --count main..<branch>` 最大者；返回候选清单（含每项的 ahead 数与是否已含 main）
- [ ] 2.3 `core/worktree_manager.py`：该查询 MUST 使用 `git worktree list` 同款的防御口径——命令超时/非零退出/异常降级 WARNING 返回空清单，MUST NOT 阻塞 boot 路径；MUST NOT 依赖 `_active_worktrees`/`_wt_branches` 内存表
- [ ] 2.4 `core/state_machine.py`：`_recovery_preserve_spec` 的 branch 解析链扩为三层——STATE.branch → `find_worktree_by_spec` → `find_branches_by_spec`；第三层命中时按 2.2 排序取最优者作 branch，并走既有 `rev-list main..branch` 非空判定与 `resolve_resume_site` 载体处置
- [ ] 2.5 `core/state_machine.py`：第三层「已含 main 但不含未合并提交」的候选（`main..branch` 为空）MUST 仍被保留判定接受为可保留锚点——该形态正是「repair 已合 main、只剩 re-merge-back」，MUST NOT 因 ahead 为 0 而落入零提交清空分支

## 3. repair 待 re-merge-back 标记（D3/C）

- [ ] 3.1 `core/pm_engine/dispatch.py`：repair run 终态 success 后、`merge_back_from_branch` 之前，写入 spec 级布尔标记 `_repair_awaiting_remerge: true`（与 1.2 的 branch 写入同一原子 `update_spec`，或紧随其后一次写入）
- [ ] 3.2 `core/pm_engine/dispatch.py`：清除点三处——re-merge-back 成功转入 `implemented` 时、同一失败链进入下一轮 repair 时、超轮次 fallback 重派时；MUST 保证 `implemented` 及之后状态上该标记恒为假
- [ ] 3.3 `core/pm_engine/dispatch.py`：repair run 运行期间 MUST NOT 写该标记（只有终态成功才写）
- [ ] 3.4 `core/state_machine.py`：`read_one`/状态迁移路径确认该字段随 spec 条目正常读写，并在降级/清空路径（`879-888`）中一并清除，避免残留污染下一轮

## 4. 恢复期消费待 re-merge-back 标记（D4）

- [ ] 4.1 `core/state_machine.py`：`recover_interrupted` 处理 `implementing` spec 时，若 `_repair_awaiting_remerge` 为真，MUST 走 re-merge-back 路径（调用既有 `merge_back_from_branch`）而非派发 implementer
- [ ] 4.2 `core/state_machine.py`：re-merge-back 成功 → 清除标记、保留 `branch`/`implementer_run`、`transition(implemented)` 并打 INFO 日志（含分支名与合并结果）
- [ ] 4.3 `core/state_machine.py`：re-merge-back 失败 → MUST 按既有冲突处理路径处理（进入 repair 或熔断计数），MUST NOT 静默清空该 spec 状态、MUST NOT 重派 implementer
- [ ] 4.4 `core/state_machine.py`：标记缺失时 MUST 回落到既有保留续做路径（2.4 的三层解析），行为与现状兼容，MUST NOT 因标记缺失报错或阻塞恢复
- [ ] 4.5 `core/state_machine.py`：`recover_interrupted` 新增的 worktree_manager 依赖与 `project_root` 缺省参数 MUST 保持「缺省时行为与旧版逐字节一致」（脚本/测试场景零变化）

## 5. 关闭期保护集与 sidecar 触发条件（D5）

- [ ] 5.1 `fenixd.py`：停机路径保护集构造增加来源 (c)——遍历 STATE 中全部 `implementing` spec，经 `find_worktree_by_spec` 把其在册 worktree 路径加入 `protected`
- [ ] 5.2 `fenixd.py`：sidecar 写入条件放宽——排水结束后仍存在收口未完成的 `implementing` spec 时，同样写入保全条目（branch 取 STATE 或事实查询，worktree 取在册记录）；MUST NOT 仅覆盖排水超时
- [ ] 5.3 `fenixd.py`：保护集构造的异常降级 MUST NOT 使保护集静默退化为空集——来源 (c) 构造失败时打 WARNING 并至少保留 sidecar 来源
- [ ] 5.4 `fenixd.py`：`cleanup_orphans` 调用前打日志记录保护集各来源 (a)/(b)/(c) 的条目数，使保护/删除可事后归因

## 6. stale 清扫的分支在飞引用保护（D6）

- [ ] 6.1 `core/worktree_manager.py`：`cleanup_stale_worktrees` 执行 `git branch -D` 前，检查该分支是否等于 STATE 中任一 `implementing`/`implemented`/`testing` spec 的 `branch` 值——命中则保留分支（worktree 目录照常删）并打 WARNING（含分支名与所属 spec）
- [ ] 6.2 `core/worktree_manager.py`：检查再增加命名空间口径——分支匹配任一 `implementing` spec 的 `<prefix>/<spec>-*` 时同样保留，覆盖锚点尚未落盘的场合
- [ ] 6.3 `core/worktree_manager.py`：状态读取失败或 STATE 不可解析时 MUST 保守处理（保留分支 + WARNING），MUST NOT 按「无引用」放行删除

## 7. 锚点不可得的强制留痕（E）

- [ ] 7.1 `core/state_machine.py`：`_recovery_preserve_spec` 在 `if not branch` 早退前 MUST 打 WARNING，内容含 spec 名与 `find_branches_by_spec` 的命中结果（候选分支名清单，无命中时显式标注「分支命名空间枚举：无候选」）
- [ ] 7.2 `core/state_machine.py`：清空重建路径（`879-888`）在写出清空状态时 MUST 打 WARNING 说明该 spec 三处锚点均不可得
- [ ] 7.3 `core/state_machine.py`：保留路径命中第三层回落时 MUST 打 WARNING，含 spec 名、选中的分支名与全部候选清单（使「选了哪个、为何选它」可检索）
- [ ] 7.4 `core/state_machine.py`：锚点已解析但 `resolve_resume_site` 判定载体不可用的既有降级 WARNING MUST 一并打出分支名与降级原因

## 8. 文档同步

- [ ] 8.1 `docs/help/03-lifecycle.md`：补充「实现产物成功即落锚点」的语义说明（`branch` 字段 = 本轮实现分支，写入时机早于 merge-back），以及 daemon 重启恢复的锚点回落链三层与其留痕
- [ ] 8.2 `docs/help/03-lifecycle.md`：补充 repair 通道的「待 re-merge-back」状态说明与重启后的处置路径（直接 re-merge-back，不重派实现者）

## 9. 测试与回归

- [ ] 9.1 新建 `tests/test_recovery_branch_anchor.py`：覆盖 1.1/1.2 的「run 成功即落锚点」（implementer 与 repair 两条），断言 merge-back 之前 STATE.branch 已非空、取值与 merge-back 后一致
- [ ] 9.2 新建 `tests/test_recovery_branch_anchor.py`：覆盖 2.1–2.5 的命名空间回落——worktree 已清只剩分支时命中保留；多候选取「已含 main」者；前缀配置生效；无候选返回空清单；命令异常降级不抛异常
- [ ] 9.3 新建 `tests/test_recovery_branch_anchor.py`：覆盖 7.1–7.4 的留痕——无锚点早退打 WARNING 且含「无候选」标识；第三层命中打 WARNING 且含全部候选
- [ ] 9.4 新建 `tests/test_repair_remerge_pending.py`：覆盖 3.1–3.3 的标记写入与清除——repair 成功即写、re-merge 成功后清除、下一轮 repair 清除、fallback 清除；断言 `implemented` 状态上标记为假
- [ ] 9.5 新建 `tests/test_repair_remerge_pending.py`：覆盖 4.1–4.3 的恢复期消费——带标记的 implementing spec 重启后走 re-merge-back 且未派发 implementer；re-merge 失败时按冲突路径处理不清空
- [ ] 9.6 新建 `tests/test_repair_remerge_pending.py`：覆盖 1.4 的顺序——断言 re-merge 成功路径中 `update_spec(branch=...)` 先于 `wm.cleanup` 被调用（mock 调用序）
- [ ] 9.7 `tests/test_interrupt_recovery_preserve.py`：补用例覆盖 2.4/2.5/4.4——三层回落链的向后兼容（STATE branch 在册时不触发第三层）、标记缺失时回落保留续做
- [ ] 9.8 `tests/test_mergeback_repair_lane.py`：补用例覆盖 repair 成功后的状态形态（标记 + branch 同时写入）与运行期不写标记
- [ ] 9.9 `tests/test_daemon_lifecycle_races.py`：补用例覆盖 5.1–5.4——sidecar 未写时保护集由来源 (c) 非空、保护集构成日志、无在飞 spec 时正常清理
- [ ] 9.10 `tests/test_daemon_lifecycle_races.py`：补用例覆盖 6.1–6.3——在飞 spec 分支不被 `git branch -D` 删除；无引用分支照常删除；STATE 不可解析时保守保留
- [ ] 9.11 `tests/test_pm_verification.py`：补一条「`branch` 非空但未合并进 main」的回归断言，固化 `verification.py:5248` 不依赖字段值判断合并状态的假设
- [ ] 9.12 全量回归：`python3 bin/run_full_suite.py --timeout 3600 --baseline main`，失败集合与基线逐字比对并归类存量/引入
