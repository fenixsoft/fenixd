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

- [ ] 1.1 `core/pm_engine/dispatch.py`：implementer run 返回终态 success 后、merge 预演与 merge-back 之前，`update_spec` 写入该 run 的 `branch` 与 `implementer_run`（含日志「锚点已提前落盘」）；run 未达终态成功时 MUST NOT 写。**写入点 MUST 定序在全部 merge 前置闸门之后**：零变更哨（`770`）、交付物守卫与缺件异议（`844-900`）、tasks.md 收口复检（`904`）均在 merge 预演（`945`）之前、且各自以 `status: ready/blocked` 早退并进入**下一轮全新派发**（唯一例外是零变更哨内的「确认型 no-op 放行」`780-793`——它直转 `implemented` + 入队 verifier，属终态成功、不留跨轮锚点）；写入点若落在它们之前，这些早退会把**本轮**锚点留在 STATE 上（本轮已放弃、下一轮另建分支），而 `_recovery_preserve_spec` 第一层先于第二层（`core/state_machine.py:905-907`）→ 下一轮在飞期间重启即整轮丢弃在飞成果，正是本 SPEC 要消除的形态。实现口径二选一 MUST 显式落地并在用例中断言：(i) 写入点紧邻 merge 预演之前（`~940`，即上述早退之后）；或 (ii) 保留早退之前的写入点，但在这三处早退分支内一并清锚点，且断言早退路径不残留本轮锚点
- [ ] 1.2 `core/pm_engine/dispatch.py`：repair run 返回终态 success 后、`merge_back_from_branch` 之前，同样先写该实现分支的 `branch`（复用 1.1 的写入点，不复制逻辑）
- [ ] 1.3 `core/pm_engine/dispatch.py`：确认既有「merge-back 成功后写 branch」的**三处**调用点（`1045` implementer、`2496` fast-track、`2776` repair re-merge）保留且取值与 1.1/1.2 一致，MUST NOT 出现两处写入不同分支名。（`1354` 不属本清单：它是 `_impl_diagnosis` 的 `progress.branch`，由 `1359-1360` 写入 `_impl_diagnosis` 字段，不是 STATE 顶层 `branch` 的写入点。）
- [ ] 1.4 `core/pm_engine/dispatch.py`：清理 `_run_repair_worker` 的写入顺序——`update_spec({branch, implementer_run, ...})` MUST 先于 `wm.cleanup(wt_path, success=True)` 执行
- [ ] 1.5 `core/pm_engine/dispatch.py`：**新实现轮次的派发入口 MUST 清除上一轮的 `branch`/`implementer_run` 锚点**（非 `_recovery_resume` 续做的全新派发；只涉及「尚无成功 run 的新轮次」，旧分支留存按既有清扫/遗产策略处理，本任务不新增保留承诺）——**实现位置 MUST 优先落在「全新实现派发的唯一入口」**（`core/pm_engine/dispatch.py:672` 的 `_run_agent_worker` → `elif agent_type == "implementer":` 分支内、`_recovery_resume` 续做判定（`:690-706`）之后、`run_implementer(...)`（`:724`）之前的 `resume_wt is None` 非续做路径；fast-track 走独立分支（`:643`），若按 1.1 纳入 D1 则须在其对应入口同样落点），使全部重派出口机械覆盖，MUST NOT 只按 `status: ready` 写点逐点枚举（枚举必然遗漏，且下游每新增一个重派出口就重新引入本缺陷）。出口清单以 `grep -n '"status": "ready"' core/pm_engine/dispatch.py` 为审计口径，实现时 MUST 记录「哪些出口经唯一入口覆盖、哪些出口不经派发而直接改状态（含人工复位 `blocked`→`ready` 后重派）」，并至少覆盖：`818`（零变更哨重派）、`1027`（merge 失败重试）、`1171`/`1185`（实现 run 失败重试）、`2108`（`_redispatch_for_missing`）、`2156`（`_redispatch_tasks_relint`）、`2482` 与 `3216`/`3225`/`3250`/`3278`（fast-track 各重试出口，若 fast-track 按 1.1 纳入 D1）、`2921`（`_fallback_after_repair`）。理由：D1 使 `branch` 在「run 成功但 merge 未完成」时即非空；若重派前不清除，`_recovery_preserve_spec`（`core/state_machine.py:905` 第一层先于 `:907` 第二层）的第一层 STATE.branch 会在**下一轮在飞期间**命中上一轮的分支，压过第二层（当前在册 worktree），恢复链将 preserve/resume 陈旧分支并整轮丢弃当前轮载体，同时违反 D1 自定的「`branch` = 本轮实现分支」语义——即本 SPEC 要消除的「丢一轮」形态在 D1 之下重新出现。口径与既有新轮次派发点一致（`dispatch.py:1416` 派发异常回滚、`engine.py:2303-2308` stuck implementing 自动恢复均已写 `branch: None`）。（替代方案：改 `_recovery_preserve_spec` 让在册 worktree 优先于 STATE.branch——会反 D2 明定的优先级与 `interrupt-recovery-preserve` 既有契约，已否决。）

## 2. 锚点的 git 分支命名空间回落（D2/B）

- [ ] 2.1 `core/worktree_manager.py`：新增按 spec 枚举候选实现分支的查询（建议名 `find_branches_by_spec`），以 `git for-each-ref refs/heads/<prefix>/<spec>-*` 为事实源。**前缀 MUST 与分支创建端同源**：创建端硬编码 `fenix/`（`core/worktree_manager.py:223` 验证分支、`:226` 实现分支），而配置 `worktree.implement_branch_prefix`（`.fenix/config.yaml:114`）现仅被 `engine._resolve_push_branch`（`core/pm_engine/engine.py:1860`）读取、非创建端事实源——故枚举前缀 MUST 取创建端口径 `fenix/`（或「配置值 ∪ `fenix/`」并集），MUST NOT 仅凭配置值取前缀（配置非 `fenix` 时创建端仍产出 `fenix/<spec>-<ts>`，仅按配置枚举会扫空命名空间、本层静默失效）；若坚持读配置取前缀，MUST 先使创建端同源（改 `:223/226` 与 `:1383`，超出本 SPEC 范围）。**候选口径 MUST 为「完整 spec 名 + 分隔符边界」全等比较**：分支名去掉 `<prefix>/` 后按最后一个 `-` 分段，末段 MUST 为纯数字时间戳、其前段 MUST 与该 spec 名全等；MUST NOT 把 glob 命中集合直接当候选——spec 名互为前缀时（`fix-x` 与 `fix-x-y`）glob 会把 `fix-x-y` 的分支算作 `fix-x` 的候选，导致跨 spec 误配（口径与 `_wt_name_matches_spec`（`core/worktree_manager.py:3201-3217`）、`engine.py:1869-1871` 的既有 `startswith(prefix/spec-)` + 末段 `isdigit()` 边界守卫一致）；`<prefix>/verify-<spec>-*` 验证分支 MUST NOT 进入候选清单。**依赖获取方式 MUST 显式落地**：`WorktreeManager` 现构造签名为 `(base_dir, project_root, logger, process_scanner=None)`（`core/worktree_manager.py:134`）且全文件无配置取值调用（对比 `engine.py:1857` 经 `self._get_config` 取同名键；若选并集方案仍须明确配置读取途径），实现 MUST 明确配置读取途径（构造注入或按 `project_root` 就地读取），并保持既有构造调用点（`fenixd.py:228` 及各测试）兼容；读取失败 MUST 降级为创建端缺省前缀而非抛错（与 2.3 同口径）
- [ ] 2.2 `core/worktree_manager.py`：候选排序实现——先取 `git merge-base --is-ancestor main <branch>` 成立者，其中取 committerdate 最新；无「已含 main」候选时取 `git rev-list --count main..<branch>` 最大者；返回候选清单（含每项的 ahead 数与是否已含 main）
- [ ] 2.3 `core/worktree_manager.py`：该查询 MUST 使用 `git worktree list` 同款的防御口径——命令超时/非零退出/异常降级 WARNING 返回空清单，MUST NOT 阻塞 boot 路径；MUST NOT 依赖 `_active_worktrees`/`_wt_branches` 内存表
- [ ] 2.4 `core/state_machine.py`：`_recovery_preserve_spec` 的 branch 解析链扩为三层——STATE.branch → `find_worktree_by_spec` → `find_branches_by_spec`；第三层命中时按 2.2 排序取最优者作 branch，并走既有 `rev-list main..branch` 非空判定与 `resolve_resume_site` 载体处置
- [ ] 2.5 `core/state_machine.py`：第三层候选 MUST 与第一/二层同口径过既有的「`main..branch` 非空」闸门——`main..branch` 为空的候选等价于分支 tip 与 main 同点（零提交分支），MUST NOT 被判为可保留锚点，MUST 走零提交清空重建路径（与 `specs/interrupt-recovery-preserve/spec.md` 的「零提交分支走现行清空」逐字节兼容，亦与 design Non-Goals 一致）。**闸门 MUST 先于排序**：零提交候选须自候选清单中剔除、不参与排序，否则 tip 与 main 同点且 committerdate 最新的候选会先被排序选中、再过不了闸门，使本可保留的其它候选被误判为不可得。注意：repair 已把 main 合入分支的形态必然 ahead ≥ 1（冲突解决提交落在分支上、不在 main），不受本条影响

## 3. repair 待 re-merge-back 标记（D3/C）

- [ ] 3.1 `core/pm_engine/dispatch.py`：repair run 终态 success 后、`merge_back_from_branch` 之前，写入 spec 级布尔标记 `_repair_awaiting_remerge: true`（与 1.2 的 branch 写入同一原子 `update_spec`，或紧随其后一次写入）
- [ ] 3.2 `core/pm_engine/dispatch.py` 与 `core/state_machine.py`：清除点四处——re-merge-back 成功转入 `implemented` 时（dispatch）、同一失败链进入下一轮 repair 时、超轮次 fallback 重派时（`_fallback_after_repair`）、§4.3 的恢复期 re-merge 失败回落保留续做时（state_machine）；MUST 保证 `implemented` 及之后状态上该标记恒为假。残留标记危害：D1 之后 `branch` 在 run 运行期即非空，带残留标记的 `implementing` spec 一旦重启会被 re-merge 进主树，而该分支上的实现可能尚未完工
- [ ] 3.3 `core/pm_engine/dispatch.py`：repair run 运行期间 MUST NOT 写该标记（只有终态成功才写）
- [ ] 3.4 `core/state_machine.py`：新标记 MUST 登记进 `StateParser._parse_content` 的布尔字段显式转换白名单（`core/state_machine.py:262-270`，现含 `frozen`/`_recovery_resume`/`_cancelled_hold`）——`_` 前缀字段虽由 `serialize` 通用写出，但解析侧只对白名单键做 bool 转换，不登记则该字段跨重启回读为字符串 `"False"`（truthy）→ 标记永不清除、恢复链恒走 re-merge；并在降级/清空路径（`879-888`）中一并清除，避免残留污染下一轮

## 4. 恢复期消费待 re-merge-back 标记（D4）

- [ ] 4.1 `core/state_machine.py`：`recover_interrupted` 处理 `implementing` spec 时，若 `_repair_awaiting_remerge` 为真，MUST 走 re-merge-back 路径（调用既有 `merge_back_from_branch`）而非派发 implementer
- [ ] 4.2 `core/state_machine.py`：re-merge-back 成功 → 清除标记、保留 `branch`/`implementer_run`、`transition(implemented)` 并打 INFO 日志（含分支名与合并结果）。**成功收口的字段与副作用 MUST 与既有 repair re-merge 成功路径对齐**（`core/pm_engine/dispatch.py:2763-2805`）：`error=None`、`_merge_fp=None`、`_merge_streak=0`、`_repair_round=0`、`_repair_merge_error=None`、`_clear_dispatch_conflict(spec_name)`、`_sync_task_progress(spec_name)`、`wm.consume_legacy(spec_name)`、`_reconcile_impl_budget(spec_name)`。残留字段的危害：`_repair_round`/`_merge_streak` 会跟随到 `implemented` 及其后的实现轮次，使下一次 bug-found 重实现时 merge 失败会带着上一轮的熔断计数。verifier 派发可由 boot 的 `event_bus.full_scan()`（`fenixd.py:409` → `event_bus.py:122/167-181`）兜底，故不强制复刻 `_enqueue_front(spec_name, "verifier")`，但用例 MUST 断言该 spec 不长期滞留 `implemented`。**依赖接线 MUST 显式落地**：`core/state_machine.py` 无 `pm_engine`/`agent_runner` 的 import 或调用（仅 3 处注释提及模块名，`core/state_machine.py:149/171/175`；构造仅取 `state_path`/`logger`），而本任务要求的副作用中 `_reconcile_impl_budget`（`core/pm_engine/budget.py:205`）、`_sync_task_progress`（`core/pm_engine/engine.py:975`）、`_clear_dispatch_conflict`（`core/pm_engine/recovery.py:326`）均为 PMEngine 侧方法，`recover_interrupted` 内**不可达**——按 4.2 字面实现只能静默省略这些回写，留下「repair 熔断计数跟随到 implemented」的既有危害。实现 MUST 二选一并显式声明：(i) 给 `recover_interrupted`（或 `_recovery_remerge_pending` 同类新方法）增加收口回调形参，由 `fenixd.py:381` 注入 PMEngine 侧实现，缺省 None 时行为与旧版逐字节一致；(ii) 把 D4 的 re-merge-back **驱动**移出 `StateMachine` 落到 PMEngine/fenixd 层（`recover_interrupted` 只登记「待 re-merge 的 spec 清单」交调用方消费）。`wm.consume_legacy` 不在此列（`worktree_manager` 已是既有形参）。用例 MUST 断言这些回写在恢复期 re-merge 成功后确实发生（而非只断言状态字段）
- [ ] 4.3 `core/state_machine.py`：re-merge-back 失败 → 清除该标记后**回落既有的保留续做路径**（`_recovery_preserve_spec`：保留 branch/implementer_run + `_recovery_resume`），使 spec 落到 `ready`，由下一轮 run 的正常 merge-back 经 `_should_enter_repair`（`core/pm_engine/dispatch.py:2554`）进入既有 repair/熔断通道。实现约束：(i) MUST NOT 静默清空该 spec 状态（分支成果保留）；(ii) MUST NOT 让 spec 停在 `implementing`——`event_bus._recover_one`（`core/event_bus.py:146-181`）无 `implementing` 分支、`recover_interrupted` 是 boot 一次性扫描（`fenixd.py:381`），停留即死锁到下次重启（且每次重启重复失败）；(iii) 若改走其它出路（如把冲突信息经 fenixd 转交 dispatch 的 repair 入口），MUST 在同一提交内显式落地该接线与新增依赖并在任务清单声明，不得留空
- [ ] 4.4 `core/state_machine.py`：标记缺失时 MUST 回落到既有保留续做路径（2.4 的三层解析），行为与现状兼容，MUST NOT 因标记缺失报错或阻塞恢复
- [ ] 4.5 `core/state_machine.py`：`recover_interrupted` 新增的 worktree_manager 依赖与 `project_root` 缺省参数 MUST 保持「缺省时行为与旧版逐字节一致」（脚本/测试场景零变化）

## 5. 关闭期保护集与 sidecar 触发条件（D5）

- [ ] 5.1 `fenixd.py`：停机路径保护集构造增加来源 (c)——遍历 STATE 中全部 `implementing` spec，把其**全部**在册 worktree 路径加入 `protected`。实现约束：`find_worktree_by_spec`（`core/worktree_manager.py:3116`）在「同一 spec 存在多个在册 worktree」时**歧义返回 None**，此时来源 (c) 命中为空、保护集仍会退化——正与「保护集 MUST NOT 退化为空集」相悖（多 worktree 恰恰是「impl 已清只剩 repair」以外的常见形态）。故来源 (c) MUST NOT 只依赖该单值查询：或新增按 spec 列全部候选的查询（复用 `_wt_name_matches_spec` 口径），或对歧义情形显式取全部候选取并集
- [ ] 5.2 `fenixd.py`：sidecar 写入条件放宽——排水结束后仍存在收口未完成的 `implementing` spec 时，同样写入保全条目（branch 取 STATE 或事实查询，worktree 取在册记录）；MUST NOT 仅覆盖排水超时。注意 `_preserve_interrupted_runs` 是 run_id 驱动（`fenixd.py:1512`）且调用点被 `if remaining:` 包住（`fenixd.py:1717-1721`）——MUST 改由「STATE 中 `implementing` spec」独立驱动并把调用点移出该 `if`，否则本事故形态（`remaining == []`）下分支永不执行；该函数返回值同时是 WIP checkpoint 输入（`fenixd.py:1742`）与保护集来源，来源 (c) 条目 MUST 一并进入二者。**run_id 取值口径 MUST 显式落地**：改由 spec 驱动后 sidecar 条目的 `run_id` 取该 spec 的 STATE.`implementer_run`（D1 落地后该字段在 run 成功即非空），缺失时留空串——该字段无生产消费者（两处消费者只读 `spec`/`worktree`，见 `fenixd.py:1605-1609` 的 WIP checkpoint 映射与 `:1755-1763` 的保护集构造，均不读 `run_id`），故空值无副作用；MUST NOT 为凑 run_id 回退 `_spec_from_run_id` 反查（会把「STATE 无 implementer_run」的形态重新排除在外）
- [ ] 5.3 `fenixd.py`：保护集构造的异常降级 MUST NOT 使保护集静默退化为空集——来源 (c) 构造失败时打 WARNING 并至少保留 sidecar 来源
- [ ] 5.4 `fenixd.py`：`cleanup_orphans` 调用前打日志记录保护集各来源 (a)/(b)/(c) 的条目数，使保护/删除可事后归因

## 6. stale 清扫的分支在飞引用保护（D6）

- [ ] 6.1 `core/worktree_manager.py`：`cleanup_stale_worktrees` 执行 `git branch -D` 前，检查该分支是否等于 STATE 中任一 `implementing`/`implemented`/`testing` spec 的 `branch` 值——命中则保留分支（worktree 目录照常删）并打 WARNING（含分支名与所属 spec）。两项实现约束：(i) **STATE 获取方式 MUST 显式落地**——`WorktreeManager` 当前不持有 state_machine（`core/worktree_manager.py:134`），实现 MUST 明确注入或就地解析 `.fenix/STATE.md` 的途径，并保持既有构造调用点兼容；(ii) 状态集 MUST 一并覆盖 **`ready` 且带 `_recovery_resume` 标记**的 spec——§4.3 的失败回落正是把 spec 落到该形态（`core/state_machine.py:955-970`），其 `branch` 即「被保留待续做」的载体。多数情形下 `resolve_resume_site` 已把载体登记进活动集、被 `cleanup_stale_worktrees` 的前置跳过覆盖（`core/worktree_manager.py:1827`），但口径本身 MUST 与 D6 的「宁可多留分支」一致，MUST NOT 依赖该间接保护
- [ ] 6.2 `core/worktree_manager.py`：检查再增加命名空间口径——分支按「完整 spec 名 + 分隔符边界」全等匹配任一 `implementing` spec 的 `<prefix>/<spec>-<ts>`（口径同 2.1：`<prefix>` 与分支创建端同源，即 `fenix/`；末段为纯数字时间戳、其前段与 spec 名全等）时同样保留，覆盖锚点尚未落盘的场合
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
- [ ] 9.2 新建 `tests/test_recovery_branch_anchor.py`：覆盖 2.1–2.5 的命名空间回落——worktree 已清只剩分支（该分支 ahead ≥ 1）时命中保留；多候选取「已含 main」者；**前缀与创建端同源**（创建端口径 `fenix/` 生效；且当配置 `worktree.implement_branch_prefix` 与创建端分歧为非 `fenix` 值时，枚举 MUST 仍命中创建端产出的 `fenix/<spec>-<ts>` 分支，MUST NOT 因仅按配置枚举而返回空清单）；无候选返回空清单；零提交候选（分支 tip 与 main 同点、`main..branch` 为空）MUST NOT 被判为可保留锚点（走清空重建）；命令异常降级不抛异常；**spec 名互为前缀**（`fix-x` 与 `fix-x-y` 的分支同时在命名空间）时 `fix-x-y` 的分支 MUST NOT 进入 `fix-x` 的候选清单、`<prefix>/verify-<spec>-*` 亦 MUST NOT 进入；**闸门先于排序**——同时存在「零提交且 committerdate 最新」与「相对 main 有提交」的候选时 MUST 选中后者而非判为不可得
- [ ] 9.3 新建 `tests/test_recovery_branch_anchor.py`：覆盖 7.1–7.4 的留痕——无锚点早退打 WARNING 且含「无候选」标识；第三层命中打 WARNING 且含全部候选
- [ ] 9.4 新建 `tests/test_repair_remerge_pending.py`：覆盖 3.1–3.3 的标记写入与清除——repair 成功即写、re-merge 成功后清除、下一轮 repair 清除、fallback 清除；断言 `implemented` 状态上标记为假；并加 STATE.md 往返断言（写 true 后重读为真；清除写 False 后重读为假，防字符串 `"False"` truthy）
- [ ] 9.5 新建 `tests/test_repair_remerge_pending.py`：覆盖 4.1–4.3 的恢复期消费——带标记的 implementing spec 重启后走 re-merge-back 且未派发 implementer；re-merge 失败时回落保留续做、标记被清除；断言恢复返回后无 spec 停留在 `implementing`（死锁回归）
- [ ] 9.6 新建 `tests/test_repair_remerge_pending.py`：覆盖 1.4 的顺序——断言 re-merge 成功路径中 `update_spec(branch=...)` 先于 `wm.cleanup` 被调用（mock 调用序）
- [ ] 9.7 `tests/test_interrupt_recovery_preserve.py`：补用例覆盖 2.4/4.4——三层回落链的向后兼容（STATE branch 在册时不触发第三层）、标记缺失时回落保留续做；并确认既有「零提交分支走现行清空」用例在改动后仍逐字节通过（不得因 2.5 修订而被改写为保留）
- [ ] 9.8 `tests/test_mergeback_repair_lane.py`：补用例覆盖 repair 成功后的状态形态（标记 + branch 同时写入）与运行期不写标记
- [ ] 9.9 `tests/test_daemon_lifecycle_races.py`：补用例覆盖 5.1–5.4——sidecar 未写时保护集由来源 (c) 非空、保护集构成日志、无在飞 spec 时正常清理；并加一条「某 implementing spec 存在**多个**在册 worktree」的保护集用例（断言全部候选进入保护集，MUST NOT 因 `find_worktree_by_spec` 歧义返回 None 而漏保护）
- [ ] 9.10 `tests/test_daemon_lifecycle_races.py`：补用例覆盖 6.1–6.3——在飞 spec 分支不被 `git branch -D` 删除；无引用分支照常删除；STATE 不可解析时保守保留
- [ ] 9.11 `tests/test_pm_verification.py`：补一条「`branch` 非空但未合并进 main」的回归断言，固化 `verification.py:5248` 不依赖字段值判断合并状态的假设
- [ ] 9.12 全量回归：`python3 bin/run_full_suite.py --timeout 3600 --baseline main`，失败集合与基线逐字比对并归类存量/引入
- [ ] 9.13 新建 `tests/test_recovery_branch_anchor.py` 补用例覆盖 1.5 的陈旧锚点回归——构造「第一轮 run 成功落锚点 → merge-back 失败降级 ready → 第二轮全新派发生成新分支」后断言第二轮在飞期间 STATE 不残留上一轮 `branch`；并加一条恢复链回归：陈旧锚点在场 + 本轮在册 worktree 在场时，`_recovery_preserve_spec` MUST NOT 选中陈旧分支（模拟 daemon 在第二轮在飞时重启，断言保留的是本轮分支）；再加一条降级 `ready` 后的存活探测回归：`_ready_has_live_child`（`core/event_bus.py:255-297`）的结论在 D1 落地前后 MUST 一致——其生产路径经 `agent_runner.has_live_attempt`（`core/agent_runner/runner.py:4824`）落到 `_stream_recent` 的 **spec 级 run jsonl 新鲜度**判定（`core/agent_runner/liveness.py:23` 窗口 120s、`:232-258`），其 STATE 兜底步（`_latest_impl_run_file`）同样委托 `find_impl_run_file` 按 `impl-<spec>-*.jsonl` glob 取最新（`core/run_task_track.py:63-83`，docstring 明载不以 STATE 定位），**三步全程不读 STATE.implementer_run**；故用例 MUST 断言「D1 未新增跳过重派的原因」，MUST NOT 断言「ready 窗口内不跳过重派」——后者会要求改写存活探测语义（本身即超出本 SPEC 范围，且与 `interrupt-recovery-preserve` 的「有存活子进程不得重置」契约冲突）
- [ ] 9.14 新建 `tests/test_recovery_branch_anchor.py` 补用例覆盖 1.1 的**写入点定序**与 1.5 的**唯一入口**两项约束：①构造零变更哨命中（`dispatch.py:770`）、交付物守卫缺件异议（`844-900`）、tasks.md 收口复检（`904`）三条早退路径，各断言其在 merge 预演前早退后 STATE MUST NOT 残留**本轮** `branch`/`implementer_run`（口径二选一按 1.1 声明落地：写入点后置则这些路径上根本不写；写入点前置则三条早退分支内一并清锚点）；②对 1.5 的「唯一入口」做**机械覆盖**断言——取至少一个**未在 1.5 清单中逐一枚举**的重派出口（如人工复位 `blocked`→`ready` 后经 `full_scan` 的普通派发），断言全新派发路径上旧锚点已被清除；该用例 MUST NOT 依赖 1.5 的行号清单（清单是审计口径、非实现口径），否则唯一入口的价值被架空
