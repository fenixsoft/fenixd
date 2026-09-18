## Context

### 事故现场（2026-09-18，实证）

`fix-recovery-path-blockers`（`mode: fast-track`）在 12:54 起跑，到 13:23 已产出 5 个提交（`7dec99c0` 驱动判定修正 / `602ebd13` wip checkpoint / `fd984716` 派发互斥守卫 / `8b38fd8c` 预算耗尽重验日程 / `18c6c4e7` 其测试），tasks.md 1.1–3.7 共 13 项已勾选。15:17 daemon 重启，日志显示恢复链**判定正确**：

```
41268 Startup terminal-state sweep: 补写 2 个遗留 无终态 run 的 interrupted 终态 ...
41273 Recovering interrupted SPEC: fix-recovery-path-blockers (was implementing)
41274 Recovery preserve: STATE branch 缺失，经 git 事实查询回落 spec ... → branch 'fenix/...-1789736042'
41275 Recovering interrupted SPEC '...' with preserved branch '...' (ahead of main) — resume continuation, worktree=.../impl-...-1789736042
41276 Updated SPEC ... {"status": "ready", "branch": "fenix/...-1789736042", "_recovery_resume": true, ...}
```

下一拍，两秒后：

```
41309 Updated SPEC ... {"branch": null, "implementer_run": null, "_repair_awaiting_remerge": false}
41311 Creating worktree: .../impl-fix-recovery-path-blockers-1789744672 on branch fenix/...-1789744672
```

新分支相对 main **0 提交**、tasks.md **0 勾选**——上一轮成果整轮丢弃。

### 代码定位

`_recovery_resume` 的消费逻辑**只写在 implementer 分支**（`core/pm_engine/dispatch/queue.py:562-600`）：读标记 → `wm.resolve_resume_site` → `pre_wt_path` → `mark_reused` → **仅 `resume_wt is None` 时清锚点**。

fast-track 走独立分支（`queue.py:505-550`），该分支对 `_recovery_resume` **零引用**，只有一段无条件的：`if 任一旧锚点存在 → {"branch": null, "implementer_run": null, "_repair_awaiting_remerge": false}`。注释明写其动机是 `fix-recovery-branch-anchor D1`——「新轮次派发前清除上一轮锚点」，前提是「**非 `_recovery_resume` 续做**的全新派发」，但 fast-track 分支把这个限定条件丢了。

同时 `_take_reusable_worktree` 兜不住：该 run 是被 SIGKILL 打断（`interrupted`），从未走终态 `keep_for_reuse`（`runner.py:2708`），`_legacy` 表无记录；且该表是**内存态、daemon 重启即失**（`legacy_registry.py` 注释与实现均确认），故 even if 它走过 keep 也救不了跨重启场景。

### 约束

- fast-track 是常规车道（`.spec.yaml mode: fast-track`），非边缘路径。
- `pre_wt_path` 目前只有 `run_implementer` / `run_repair` 支持；`run_fast_track` 无此形参（`runner.py:1077-1085`）。
- prompt 的 `_recovery_resume_note` 只挂在 implementer 分支（`prompt_builder.py:278`）；fast-track 分支只挂 `_fast_track_reuse_note`（`prompt_builder.py:359`）。
- 相邻 spec `fix-recovery-branch-anchor-without-worktree` 已合 main（`75ca10b7`），但其能力 `recovery-branch-anchor` 尚未归档（spec 处 `pushed`），不在 `spec/specs/` 中——故本变更不对其发 MODIFIED，全部行为增量收敛于新能力。
- 归档的 `interrupt-recovery-preserve` 的「恢复保留分支续做」requirement 已要求「恢复续做的 spec 复用既有 resume 派发语义」，本变更是该要求在 fast-track 车道的**补齐**，不改变其排水/停机语义。

## Goals / Non-Goals

**Goals:**

1. fast-track 车道与 implementer 车道在恢复续做语义上**同源**：同一 `_recovery_resume` 契约、同一 `resolve_resume_site` 三态解析、同一「消费后才决定是否清锚点」顺序。
2. 恢复载体经 `pre_wt_path` 从 dispatch 层贯通到 runner，续做轮**不新建 worktree**、走既有 `claude --resume` 断点续跑。
3. 恢复续做继承注记注入 fast-track prompt，使 Agent 知道「有已提交成果、从第一个未勾选项继续」。
4. 全部 fast-track 派发出口的锚点处置矩阵完备，无「无条件抹除可续做锚点」的出口；两处**有意**清锚点出口（auto-recovery / 异常回滚）的区分在代码中固定。
5. 「本轮是续做还是从零」在日志中可直接判读。

**Non-Goals:**

1. 不合并 fast-track 与 implementer 两条车道。
2. 不改动 `recovery-branch-anchor` 的锚点解析回落链（三层顺序、候选排序、命名空间枚举口径均不动）。
3. 不改排水窗口时长、停机语义、`_recovery_resume` 的「一次性消费」语义。
4. 不引入 `_legacy` 表的持久化（跨重启复用遗产是另一个更大的议题，本变更靠 `resolve_resume_site` 的 git 事实解析而非内存表）。
5. 不改 repair lane 的载体解析逻辑（仅衔接 fast-track 规模降级出口）。
6. 不删除 `.claude/worktrees/impl-fix-recovery-path-blockers-1789736042`（旧现场处置由人工操作，见 Migration Plan）。

## Decisions

### D1｜消费逻辑镜像而非提取共享函数

**选择**：在 fast-track 分支内**镜像** implementer 分支的消费序列（读标记 → `resolve_resume_site` → `mark_reused` → `仅未命中才清锚点`），保持两条分支结构对称、可逐行对照。

**备选**：把消费逻辑提取为独立方法（如 `_resolve_recovery_resume(spec_name) -> (resume_wt, resume_branch)`），两条分支共同调用。

**理由**：提取共享方法更 DRY，但两条分支的后续动作有实质差异——implementer 分支有 task-gate 计数清零、`_repair_awaiting_remerge` 失效等；fast-track 分支有规模预检降级、`_fast_track_scale_tier` 标记。强行提取会把差异塞进参数，反而降低可读性。**本项目已有先例**：`queue.py` 的 fast-track 分支在 `fix-recovery-branch-anchor D1` 落地时就是「注释明写『fast-track 车道同 implementer 语义』+ 镜像结构」，本次沿同一模式补齐，diff 最小、对照最直观。

**代价**：两份结构需同步维护。以 spec 中的矩阵要求 + 双向对照注释缓解。

### D2｜清锚点动作的精确落点

**选择**：清锚点（`{"branch": None, "implementer_run": None, "_repair_awaiting_remerge": False}`）MUST 位于续做判定**之后**，且以 `resume_wt is None` 为前置条件；同时 `_fast_track_scale_tier` 写入保持原位（它不属于「本轮锚点」，清不清与续做无关）。

**关键定序问题**：fast-track 分支当前把「规模预检结果写入」与「清锚点」放在一起。规模预检若判 `full` 会**提前 return**（降级重派 implementer）。此时若已清锚点，降级后的 implementer 派发将看不到 `_recovery_resume`——故清锚点 MUST 排在规模预检 return 之前不可行。

**落点**（精确到该分支内的顺序）：

1. 规模预检 → `full` 档则降级并 return（**此处 MUST NOT 触碰锚点**，见 D4）；
2. 写入/清除 `_fast_track_scale_tier`；
3. `_increment_impl_run_budget_used`；
4. **续做判定**：读 `_recovery_resume` + `branch` → `resolve_resume_site` → 消费标记 → `mark_reused` + 日志；
5. **仅当 `resume_wt is None`**：清锚点（旧锚点存在时）+ 陈旧 `_repair_awaiting_remerge` 失效；
6. `_run_fast_track_worker(spec_name, resume_wt)`。

注意顺序 3 与 4 的关系：预算计数 MUST 保持【当前】位置（在规模预检 return 之后、run 启动之前）——它反映「本次 fast-track run 启动」，与续做判定无关。

### D3｜载体透传用形参而非新机制

**选择**：`run_fast_track(spec_name, pre_wt_path=None)` 透传至 `_execute_agent`。

**备选**：让 runner 自己在 `run_fast_track` 内查 `_recovery_resume` 并解析载体。

**理由**：载体解析需要 `worktree_manager`，runner 虽持有它，但**消费标记**（写 `_recovery_resume: None`）是状态机写操作，属 dispatch 层职责；且 implementer/repair 的既有分工就是「dispatch 解析载体 → 传 `pre_wt_path`」。沿用既有分工，不新增第二处标记消费点（否则两处消费会有竞态与顺序问题）。

### D4｜规模预检降级出口的锚点处置

**选择**：`_downgrade_fast_track_scale`（`fast_track.py:84`）MUST NOT 清空 `branch`/`implementer_run`；它只写 `status: ready` + error 文案 + 重新 `_enqueue(spec_name, "implementer")`。

**理由**：降级后走 implementer 车道，而 implementer 分支**本来就会正确消费** `_recovery_resume`——标记与锚点应当完好地交给它。现状该降级路径不碰锚点（已符合），本决策是把它**固化为要求**并加测试，防未来重构误加清锚点。同理，降级路径 MUST NOT 消费标记。

### D5｜两处有意清锚点出口的书面区分

**选择**：在 `engine.py` 的 auto-recovery（stuck implementing）与 `rollback.py` 的派发异常回滚两处清锚点语句旁，加注释固定其与 `_recovery_resume` 的区分：

- **auto-recovery**：判据是「滞留 implementing 超阈值**且无存活子进程**」——已确认 run 死亡，属有意重置。此处 MUST NOT 消费 `_recovery_resume`；其锚点清除使随后的派发走全新路径（正确）。
- **rollback**：run **从未启动**（派发异常）——`_recovery_resume` 尚未被消费、锚点亦非本轮产出，MUST NOT 消费该标记。

**理由**：本变更的判据是「清锚点前 MUST 先消费 `_recovery_resume`」，若不固定这两处的语义，后续审查容易把它们误判为同类缺口并「修复」，反而破坏既有正确行为。

### D6｜prompt 段落去重

**选择**：fast-track prompt 注入恢复续做注记时，与既有 `_fast_track_reuse_note` **互斥**——二者语义重叠（均为「延续已有成果」），同一次构建 MUST NOT 同时注入两条。

**实现口径**：`_recovery_resume_note` 与 `_fast_track_reuse_note` 都基于 `wm.get_reuse_record(spec_name)`，而续做路径的 `mark_reused` 与复用路径的 `_take_reusable_worktree` 写的是**同一张 `_active_reuse` 表**——故二者要么都命中要么都不命中，天然互斥。实现上让恢复续做注记**优先**（它是更精确的说明：指明了中断原因），命中时以它替代 reuse 注记。

**备选**：两条都注入，靠文案自证不重复。**理由（否决）**：两段都在说「不要重做」，冗余注入浪费 token 且稀释注意力。

### D7｜不引入跨重启的复用遗产持久化

**选择**：续做完全依赖 `resolve_resume_site` 的 **git 事实解析**（分支存在性 + worktree 注册 + 目录在场），不把 `_legacy` 内存表落盘。

**理由**：`_legacy` 表是「死亡 run 现场」的登记，语义是「未提交半成品保留」；而恢复续做的载体在**分支层面**已经完整（已提交成果在 git refs 中），`resolve_resume_site` 的 `WT_REBUILDABLE` 分支能从分支重建 worktree——**未提交现场会丢**，但那属既有 `interrupt-recovery-preserve` 的已知边界（该 spec 的保全 sidecar 管未提交现场，与本节无关）。本变更不扩大范围。

### D8｜测试落点

**选择**：
- `tests/test_fasttrack_recovery_resume.py`（new）：续做命中不抹锚点 / 载体贯通不新建 worktree / 标记一次性消费 / 降级留痕 / 无标记时行为不变；
- `tests/test_fast_track_scale_precheck.py`（modify）：补降级出口不清锚点、不消费标记的用例；
- `tests/test_interrupt_recovery_preserve.py`（modify）：补 fast-track 分支的端到端续做用例（含 prompt 注记）。

**理由**：既有 `test_interrupt_recovery_preserve.py` 已建立恢复链的测试设施，续做行为属同一契约面，就近扩展。

## Risks / Trade-offs

- **[风险] 续做轮继承的 worktree 可能含上一轮未提交的脏现场，Agent 误判** → 缓解：prompt 注记明确「中断前未提交的现场（如有）同样在你的工作目录中，可审阅后继续使用」（沿用 implementer 分支既有文案语义），把判断权交给 Agent；同时 D7 明确该边界不属本变更范围。

- **[风险] 镜像结构与 implementer 分支再次漂移**（未来改一边忘改另一边）→ 缓解：spec 中「派发入口消费恢复续做标记」requirement 明确要求「与 implementer 分支同源消费、判据与顺序逐条对齐」；两处代码互相加对照注释；测试覆盖两条车道的同一场景。

- **[风险] 规模预检降级与续做的交互**（降级后 implementer 派发是否能拿到标记）→ 缓解：D4 明确降级路径不消费标记、不清锚点；测试覆盖「带标记的 fast-track spec 被降级 → implementer 派发命中续做」。

- **[风险] 续做载体解析失败时的降级路径把锚点清了，但旧分支成果仍在**（下一次重启仍走分支命名空间回落）→ 缓解：这是 `recovery-branch-anchor` 兜底链的设计意图（三层回落），本变更不削弱；降级时打 WARNING 留痕但不额外动作。

- **[取舍] 「消费后才决定是否清锚点」使 fast-track 分支的代码行数增加约 25 行** → 接受：这是与 implementer 分支对齐的必要成本；共享提取方案已被 D1 否决。

## Migration Plan

1. 代码落地后无状态迁移：`_recovery_resume` 与 `branch` 字段语义不变，存量 STATE 零迁移。
2. **本次事故的存量现场需人工处置**：`fix-recovery-path-blockers` 的旧分支 `fenix/fix-recovery-path-blockers-1789736042`（5 提交 + 旧 worktree 内 tasks.md 未提交勾选）与新 run 的分支并存。修复落地后，若要挽回旧成果，由人工在新一轮派发前把旧分支的 tasks.md 勾选与改动合并处理（或直接让旧分支的成果经 merge-back 收口）；**该操作 MUST NOT 写成 SPEC 任务**（主树专属写操作 + 需人工裁决，Agent 无法在 worktree 内完成）。
3. 回滚策略：本变更为纯增量（新增形参、新增分支内逻辑），回滚即还原 `queue.py` fast-track 分支到「无条件清锚点」——但那会重新引入本缺陷，故回滚应仅限紧急止血并同步记录。

## Open Questions

1. 续做轮中，`_fast_track_scale_tier` 是否需要随续做轮重算？当前实现每轮都重算并与存量标记比对，续做轮沿用同一逻辑——**倾向保持现状**（不引入新分支），但若续做轮规模档位漂移致 extension 上限变化，需另案评估。
2. `run_fast_track` 的 `pre_wt_path` 是否也应暴露给 repair lane 的 fast-track 变体？当前 repair lane 独立解析载体（`claim_legacy_for_repair`），不经 `run_fast_track`——**倾向不暴露**，保持职责边界。
