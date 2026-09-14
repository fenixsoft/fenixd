## Context

2026-09-14 `fix-impl-tasks-completion-gate` 滞留 7h42m 的完整因果链（五环，均已回源码核实）：

```
环1  core/pm_engine/dispatch.py:2774-2785 / :2497 / :1045
     branch 只在 merge-back 成功后才写 STATE；repair 通道全程不写 → 事故 spec 17 条 state 更新中无一条写过非空 branch
环2  fenixd.py:1718-1721
     _preserve_interrupted_runs 仅在 drain_wait 返回非空时触发；repair agent 在排水窗口内自行退出 → remaining=[] → sidecar 从未写
环3  fenixd.py:1749  protected = set(preserved_wts) → 空集
     cleanup_orphans(protected=∅) 于 21:36:40.026 删除 repair worktree（此刻它仍在 git worktree list 注册表中）
环4  core/state_machine.py:905-919
     branch=None → 回落 find_worktree_by_spec（只读 git worktree list，不扫 git branch）→ None → if not branch: return False（静默）
     而 fenix/fix-impl-tasks-completion-gate-1789318103 一直在 git refs 里、已 merge main、可 fast-forward
环5  core/state_machine.py:879-888  清空 status/branch/implementer_run → full_scan → 新分支从零重写
```

现状约束与既有资产：

- `_recovery_preserve_spec`（`state_machine.py:892`）与其三态载体处置（`worktree_manager.resolve_resume_site`）已具备「worktree 缺失则从分支重建」的能力——**唯一缺的是「叫出分支名」这一步**。本变更不重建该机制，只补锚点来源。
- `fix-preserve-chain-first-round-gap`（09-12）已把回落源从「STATE 单一来源」扩到「在册 worktree」，但其 docstring 明确「STATE `branch` 保留为完成态记录，语义不变」。本变更处理该取舍留下的窗口。
- repair 通道运行期 `status` 保持 `implementing`（`dispatch.py:2584` 不改 status），且 `_repair_round` 在「派过一轮」与「已成功待合并」两态同值——**现状无任何持久化字段能区分二者**。
- `branch` 字段消费点普查（全仓 grep）结论：唯一按「是否已合并」做分支判定的消费点是 `core/pm_engine/verification.py:5248-5253`，其判据是 `_branch_merged_into_tree(branch)` → `git merge-base --is-ancestor`（问 git，不问字段）。其余消费点为展示（`dashboard/data.py:3652`、`bin/fenix_process.py:230`）或取值直用（`engine.py:1804/1857`、`dispatch.py:691`）。

## Goals / Non-Goals

**Goals:**

- 消除「已实现 / 已修复、未合并」这一窗口的恢复失明：daemon 重启后必须能找到该 spec 的实现分支并保留续做（或直接完成合并），而非清空重写。
- 关闭期保护集不得因「排水正常完成」而退化为空集。
- 锚点缺失成为**可检索的日志事件**，而非静默早退。
- 消除 happy path 上「先删载体、后写锚点」的顺序窗口。

**Non-Goals:**

- 不改排水窗口时长、不改快速停机语义、不引入自适应延长排水。
- 不改 repair 轮次上限、熔断阈值、fallback 重派语义。
- 不改 `interrupt-recovery-preserve` 既有的「零提交分支走清空」兼容分支。
- 不为 `.fenix/restart_request` 的写入者做归因（本次重启由 planned restart 触发，属正常流程）。
- 不引入新的配置键。

## Decisions

### D1｜`branch` 语义改为「本轮实现分支」，而非新增独立字段

**选择**：把 `branch`/`implementer_run` 的写入时机从「merge-back 成功」提前到「run 终态成功」，字段语义随之由「已合并分支」变为「本轮实现分支」。

**理由**：
- 字段**取值集合完全不变**（同一分支名），仅时机提前；唯一的语义差异是「分支存在但尚未合并进 main」这一中间态现在可从 STATE 观察到。
- 消费点普查（见 Context）证明：唯一关心「是否已合并」的消费点问的是 git 而非字段值。其余消费点要么展示、要么直用取值。
- 新增字段（如 `_impl_branch`）会与 `branch` 长期并存并漂移：恢复链、Dashboard、push 校验都需要同时读两个字段，「哪个是真的」将成为新的 bug 温床。

**替代方案（已否决）**：
- *新增 `_impl_branch` 字段*：字段漂移与双读点，且 `recovery-branch-anchor` 的回落链会变成四层。
- *只做 B（命名空间回落），不改写点*：也能修复本次事故，但 `branch` 在 STATE 中长期为 null 会让所有读 STATE 的下游（Dashboard、CLI、人工排查）继续失明；且每次恢复都要付一次 git 枚举代价。
- *在 merge-back 失败/进入 repair 时就写*：覆盖面比「run 成功时写」窄——普通 implementer 成功但 merge-back 尚未开始的那段窗口仍然失明。

### D2｜锚点回落链为三层，第三层按「已含 main 合并」优先排序

**选择**：`STATE.branch` → `find_worktree_by_spec`（在册 worktree）→ **分支命名空间枚举**。第三层的候选排序：先取 `main` 为其祖先者（`git merge-base --is-ancestor main <b>`），再按 committerdate 最新；无「已含合并」候选时取 `git rev-list --count main..<b>` 最大者。

**理由**：
- 第三层的事实源是 **git refs**，与 worktree 是否在册无关——这正是环 3/环 4 的缺口所在。
- 「main 是其后代祖先」这一判据精确对应「repair 已把 main 合入分支」的形态（本次事故正是此形态），比「ahead 最多」更贴近「哪个分支最接近可合并」。
- 命名空间前缀取自 `worktree.implement_branch_prefix` 配置（缺省 `fenix`），与 `engine.py:1857` 的既有 refs 回落口径一致，避免硬编码。
- 多候选时**取最优 + WARNING 列全部候选**，而非 `find_worktree_by_spec` 的「歧义返回 None」：后者歧义是因为目录名解析可能误配，而这里 spec 名在命名空间内是精确匹配段，取最优是安全的；且返回 None 会把场景重新推回「清空重写」，与本次修复目标相悖。

**替代方案（已否决）**：
- *复用 `find_worktree_by_spec` 并让它也扫分支*：会污染该函数的契约（它返回 `(wt_path, branch)`，无 worktree 时语义不明），且其「歧义返回 None」策略不适用。
- *枚举全部 `refs/heads/**` 再按 spec 名模糊匹配*：spec 名互为前缀时（如 `fix-x` 与 `fix-x-y`）会误配——`find_worktree_by_spec` 的 docstring 已就同类风险给出「按完整 spec 名 + 分隔符边界匹配」的先例，本层沿用。

### D3｜待 re-merge-back 标记：字段名、写入点与生命周期

**选择**：新增 spec 级布尔字段（命名在实现时定为 `_repair_awaiting_remerge` 或同义），语义为「实现分支已含 main 的合并与冲突解决，仅剩重新合并进主树」。

- **写入点**：repair run 返回终态 success 之后、`merge_back_from_branch` 之前（`dispatch.py:_run_repair_worker` 内）。
- **清除点**：re-merge-back 成功转入 `implemented`；同一失败链进入下一轮 repair；fallback 重派。
- **不清除点**：repair run 运行期间（不写即无标记）；普通 implementer 路径（不涉及）。

**理由**：环 2 的根因是「进程退出 ≠ 收口完成」，而框架没有任何持久表达来承载这个区别。该标记把「收口已推进到哪一步」变成 STATE 可观察的事实，使恢复链不必靠推测。

**替代方案（已否决）**：
- *改用一个新 status 值（如 `re-merging`）*：会污染状态机的 11 态全集，牵连 Dashboard、事件总线、lint、推送流程等全部状态消费点，代价远超收益。
- *靠 `_impl_diagnosis` 的 `progress.branch` 承载*：该字段是诊断附加物（写入包在 `try/except` 内、MUST NOT 阻塞主流程），把它提升为恢复判据会把「非阻塞」契约反转，且恢复链目前完全不读它。
- *靠 run 文件里 repair run 的终态事件反推*：需要在启动路径解析历史 run jsonl，代价高且 run 文件会被归档/清理。

### D4｜恢复期 re-merge-back 由 `recover_interrupted` 直接驱动，不排队回 dispatch

**选择**：`recover_interrupted` 见到标记后，直接调用既有的 `merge_back_from_branch` 完成合并并推进 `implemented`；不经由 event_bus 排队到 dispatch 层。

**理由**：
- 恢复路径本来就在 daemon 启动的同步阶段执行，主树此刻无其他在飞 run（`fenixd.py:381` 在 `cleanup_stale_worktrees` 与 `full_scan` 之前），是最干净的执行时机。
- 排队回 dispatch 会让 spec 短暂处于 `ready`，而 `ready` 会被 `full_scan` 派发 implementer——正是要避免的行为。

**替代方案（已否决）**：
- *排队到 dispatch 的 repair 通道复用*：需要引入「re-merge only」的子状态与派发分支，且 `ready` 窗口存在误派风险。
- *只保留分支、让 implementer resume 后自行收口*：可行但浪费一轮 agent（实现已完成，agent 无事可做，仍要走一遍收工守卫与结论写盘）；作为 D3 标记缺失时的兼容回落保留。

### D5｜保护集来源 (c)：由 STATE 状态驱动，不由事件可见性驱动

**选择**：停机路径的保护集除 sidecar 来源外，增加一路——遍历 STATE 中全部 `implementing` spec，用 `find_worktree_by_spec` 把其在册 worktree 加入保护集。sidecar 写入条件同样放宽：排水结束后仍存在收口未完成的 `implementing` spec 时也写。

**理由**：环 3 的本质是「保护集由事件可见性（排水是否超时）驱动」，而收口是否完成与排水是否超时是两件事。改由**状态**驱动后，无论 sidecar 写没写、排水超没超时，在飞 spec 的载体都不会被无差别清理。代价是每次停机多几次 `git worktree list` 调用（毫秒级）。

**替代方案（已否决）**：
- *只放宽 sidecar 触发条件，保护集仍只读 sidecar*：仍需先判定「收口未完成」，而那正是缺字段的地方；改为状态驱动更简单且更强。
- *停机时干脆不清理 orphan*：会累积垃圾 worktree，且与 `cleanup_stale_worktrees` 的启动清扫职责重叠。

### D6｜分支删除的在飞引用检查口径

**选择**：`cleanup_stale_worktrees` 删分支前，检查该分支是否 (a) 等于 STATE 中任一 `implementing`/`implemented`/`testing` spec 的 `branch` 字段值，或 (b) 匹配任一 `implementing` spec 的 `<prefix>/<spec>-*` 命名空间。命中则保留分支（worktree 目录照常删），并打 WARNING。

**理由**：(b) 覆盖「锚点尚未落盘」的情况——只有 (a) 会漏掉本变更 D1 落地前的历史中间态与任何写入失败的场合。(a)+(b) 并集是廉价的保守超集，宁可多留分支（人工可删）也不可误删成果（不可恢复）。

**替代方案（已否决）**：*只按 (a) 判定*：不够保守；*对所有 `fenix/*` 分支永久保留*：无界增长。

## Risks / Trade-offs

- **[D1 使 `branch` 在 spec 未合并时即可见，下游若隐含「branch 非空 ⇒ 已合并」会误判]** → 消费点普查已逐点确认（唯一相关点是 `verification.py:5248`，问 git）；实现时 MUST 在测试中加一条「branch 非空但未合并」的 `verification.py` 回归断言，把该假设固化为测试。
- **[D2 第三层枚举在大仓库（数百分支）下增加启动耗时]** → 枚举限定在 `<prefix>/<spec>-*` 前缀下（per-spec 调用，单 spec 候选通常 ≤3）；仅在「STATE 与 worktree 双缺失」时才触发，属冷路径。实现时 MUST 为每条 git 命令保留既有 15s 超时与异常降级（返回不可得，不阻塞恢复）。
- **[D2 多候选取「committerdate 最新」在极端情形可能选中错误分支]** → 排序规则优先「main 为其祖先」，该情形下候选语义已明确；残余风险的兜底是 WARNING 全量列出候选 + 保留路径仍走 `is_available` 三态校验，不可用即降级。
- **[D4 在恢复期直接写主树（merge-back）]** → 恢复阶段主树无其他在飞 run，且 `merge_back_from_branch` 自带冲突检测与 abort 语义；失败时按既有冲突路径处理，不静默清空（已在 spec 的 Scenario 固化）。
- **[D5 保护集变大导致 orphan 清理能力下降，垃圾 worktree 累积]** → 保护集只覆盖 `implementing` 状态（在飞 spec 数量有限，实测通常 0–2）；清理仍由 `cleanup_stale_worktrees` 在启动后处理非保护项；保护集构成 MUST 打日志，可事后审计是否长期过大。
- **[D6 过早保留分支使 `git branch` 列表膨胀]** → 保留判定绑定在「在飞/待收口 spec」上，spec 归档后其分支不再受保护，可在后续清扫中回收。
- **[新标记（D3）与既有 `_repair_round`/`_repair_merge_error` 生命周期不一致造成残留]** → 清除点覆盖「re-merge 成功 / 下一轮 repair / fallback 重派」三条出口；MUST 加断言测试：`implemented` 及之后状态上该标记恒为假。

## Migration Plan

- **无数据迁移**：既有 STATE 条目缺新标记一律视为「无标记」，走既有保留续做路径（spec 已固化为 Scenario）。
- **无配置迁移**：不新增配置键。
- **上线顺序**：D1/D3 的写点与 D2/D5/D6 的读点相互独立，可同批落地；若需分批，先落读侧（D2/D5/D6）——读侧对历史数据完全兼容，且单独即可修复本次事故。
- **回滚**：改动集中在四个文件、无 schema 变更；`git revert` 单个提交即可回到现状行为。新标记字段在回滚后成为无消费方的孤儿字段，不产生副作用。
- **验证**：以 `tests/` 下的定向用例覆盖「已修复待合并窗口重启」「worktree 已清只剩分支」「保护集不退化」三条主路径；全量回归经 `bin/run_full_suite.py --timeout 3600 --baseline main` 归类存量/引入。

## Open Questions

- 无阻塞性未决项。实现时需定夺的仅有新标记的字段名（建议 `_repair_awaiting_remerge`，需与既有 `_repair_*` 前缀一致）与 `recover_interrupted` 内 re-merge-back 的失败归因文案措辞——两者均不影响本设计的结构与契约。
