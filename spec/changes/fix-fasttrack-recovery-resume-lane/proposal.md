## Why

2026-09-18 实证：`fix-recovery-path-blockers` 在 daemon 重启后**没有**继承上一轮已完成的成果（5 个提交、13 项任务勾选、`test_admin.py` +231 / `test_event_bus.py` +86 / `test_pm_verification.py` +126），而是在全新分支上从零重做——旧分支至今孤立在 `fenix/fix-recovery-path-blockers-1789736042`。

恢复链本身**判定正确、保全到位**：`state_machine` 打出了

```
Recovery preserve: STATE branch 缺失，经 git 事实查询回落 spec
'fix-recovery-path-blockers' 在册 worktree → branch 'fenix/...-1789736042'
Recovering interrupted SPEC '...' with preserved branch '...' (ahead of main)
— resume continuation, worktree=.../impl-fix-recovery-path-blockers-1789736042
```

并写入 `{status: ready, branch: <保留分支>, _recovery_resume: true}`。

但该 spec 是 `mode: fast-track`，派发经 `_run_agent_worker` 的 **fast-track 分支**（`core/pm_engine/dispatch/queue.py:505-550`）。该分支只做「新轮次派发前清除旧锚点」，**从不读 `_recovery_resume`**——implementer 分支的续做消费逻辑（`queue.py:562-600`：读标记 → `wm.resolve_resume_site` 三态解析 → `pre_wt_path` 透传 → 仅载体不可得时才清锚点）**未被镜像**。结果：state_machine 刚写入的 preserved branch 在派发当刻被 `{"branch": null, "implementer_run": null}` 就地抹除；`runner.create()` 的 `_take_reusable_worktree` 又因该 run 是被 SIGKILL 打断、从未走终态 `keep_for_reuse` 而返回 None——于是新建 worktree。

净效果：`interrupt-recovery-preserve` 为 fast-track spec 保全的分支成果**结构性不可达**。fast-track 是 `.spec.yaml mode` 的常规车道（非边缘路径），所有 fast-track spec 在每次 daemon 重启时都会整轮丢弃既得成果，且随重启次数逼近实现预算上限（本次已 `_impl_run_budget_used: 2/6`）。同一 spec 的 `_recovery_resume` 语义在两条车道上的行为分叉，属框架级不一致。

## What Changes

- **A｜fast-track 派发入口镜像续做消费（治本）**：`core/pm_engine/dispatch/queue.py` 的 `_run_agent_worker` fast-track 分支对齐 implementer 分支——读 `_recovery_resume` 标记与 `branch`，经 `wm.resolve_resume_site` 三态解析载体；**仅在 `resume_wt is None`（未命中续做）时才执行「清除旧锚点」**；命中时 `mark_reused` 登记继承痕迹并打 `Resume dispatch ...` 日志。
- **B｜runner 载体透传贯通**：`AgentRunner.run_fast_track` 接受并透传 `pre_wt_path`（现状仅 `run_implementer`/`run_repair` 支持），使 dispatch 层解析出的恢复载体进入 `_execute_agent` 的 `st.wt_path`，**不新建 worktree**、走既有 `claude --resume` 断点续跑。
- **C｜prompt 继承注记补 fast-track 分支**：`prompt_builder` 的 fast-track 分支注入 `_recovery_resume_note`（现状仅 implementer 分支注入 `prompt_builder.py:278`），向 Agent 说明「本 spec 的实现 run 曾因重启被中断、框架保留了你在分支上的已提交成果、从 tasks.md 第一个未勾选项继续、不重做不回滚」。注入 MUST 带**恢复来源判据**（`mark_reused(..., recovery=True)` + `_recovery_resume_note(..., require_recovery=True)`）：`get_reuse_record` 所读的 `_active_reuse` 同时被普通打回重派（`_take_reusable_worktree`）、跨 attempt 复用（`runner.py:2344-2350`）写入，无来源判据会把「曾因 daemon 重启被中断」的**错误归因**注入到每次普通重派轮；未命中恢复来源时 MUST 退回既有 `_fast_track_reuse_note`。（implementer 分支既有调用不传该判据，行为与文案逐字节不变。）
- **D｜锚点失效条件收窄**：「锚点随实现轮次失效」在 fast-track 车道的落点补例外——失效判定 MUST 先消费 `_recovery_resume`，**续做载体命中时 MUST NOT 清空本轮锚点**；只有「未命中续做」（无标记 / 解析降级 / 零提交）才失效。（注：`recovery-branch-anchor` 能力由尚未归档的 `fix-recovery-branch-anchor-without-worktree` 引入，不在 `spec/specs/` 中，故本变更**不**对其发 MODIFIED，改由新能力 `fasttrack-recovery-resume` 覆盖 fast-track 车道上的这一约束。）
- **E｜全部 fast-track 派发出口普查**：除首轮派发外，fast-track 的其余派发出口（规模预检降级 `full`、结果文件缺失/硬校验失败/零变更哨重派、transient 终态保留、repair lane fallback）MUST 逐一书面明确「是否消费恢复标记 / 是否清锚点 / 是否保留现场」，MUST NOT 存在无条件抹除可续做锚点的出口。`engine.py` 的 auto-recovery（stuck implementing）与 `rollback.py` 的派发异常回滚两处清锚点出口 MUST 一并纳入判据说明（前者是有意的「确认无存活子进程」重置，后者是「run 从未启动」回滚，二者与 `_recovery_resume` 的区分 MUST 在代码注释中固定）。
- **F｜可观测性**：续做命中、载体解析降级、出口清锚点三类事件 MUST 各有日志（对齐 implementer 分支的 `Resume dispatch` / `Resume site unavailable`），使「本轮是续做还是从零」在日志中可直接判读。

**BREAKING**：无。无状态字段新增（复用既有 `_recovery_resume` / `branch`）、无配置键、无数据迁移；非 fast-track 车道行为逐字节不变。

## Capabilities

### New Capabilities

- `fasttrack-recovery-resume`: fast-track 车道的恢复续做契约——(i) 派发入口 MUST 消费 `_recovery_resume` 并消费后才决定是否清锚点；(ii) 恢复载体经 `pre_wt_path` 贯通至 runner 且不新建 worktree；(iii) 继承注记 MUST 注入 fast-track prompt；(iv) 全部 fast-track 派发出口的「消费/清锚点/保留现场」矩阵 MUST 完备且无无条件抹除。

### Modified Capabilities

（无。`recovery-branch-anchor` / `interrupt-recovery-preserve` 中与本变更相邻的约束，前者能力尚未归档（`fix-recovery-branch-anchor-without-worktree` 仍处 `pushed`，不在 `spec/specs/`），后者语义不变——本变更的全部行为增量收敛于新能力 `fasttrack-recovery-resume`。）

## Impact

**代码**

| 文件 | 改动 |
|---|---|
| `core/pm_engine/dispatch/queue.py` | fast-track 分支镜像 implementer 的 `_recovery_resume` 消费（读标记 → `resolve_resume_site` → `pre_wt_path` → 仅未命中才清锚点 → `mark_reused` + 日志） |
| `core/agent_runner/runner.py` | `run_fast_track` 增加 `pre_wt_path` 形参并透传 `_execute_agent` |
| `core/agent_runner/prompt_builder.py` | fast-track 分支按「恢复来源」判据择一注入恢复续做注记 / `_fast_track_reuse_note`；`_recovery_resume_note` 增加可选 `require_recovery` 形参（缺省不变） |
| `core/worktree_manager/legacy_registry.py` | `mark_reused` 增加可选 `recovery` 形参（记录恢复来源，供 prompt 判据；缺省不写键） |
| `core/pm_engine/dispatch/fast_track.py` | 全部重派出口的「消费/清锚点/保留现场」判据书面固定（含 `_downgrade_fast_track_scale` 降级 full 时的续做衔接） |
| `docs/help/03-lifecycle.md` | 补 fast-track 车道的恢复续做语义说明 |

**行为**：daemon 重启后 fast-track spec 的恢复续做命中率提升至与 implementer 车道一致；「整轮丢弃 × 每次重启」的预算浪费被消除。`branch` 字段在续做轮次中的取值由「被清空」变为「保留既有分支」，Dashboard 与 `bin/fenix_process.py` 的分支展示相应变化（属预期修复）。

**兼容性**：无新增 STATE 字段；`_recovery_resume` 仍是「一次性消费」标记（派发后清空），语义不变；无配置项变更。

**非目标**：不改变 `interrupt-recovery-preserve` 的排水窗口与停机语义；不改变 `recovery-branch-anchor` 的锚点解析回落链（三层顺序与候选排序不变）；不引入「fast-track 与 implementer 车道合并」；不改变 repair lane 的载体解析逻辑（仅衔接 fast-track 的降级出口）。
