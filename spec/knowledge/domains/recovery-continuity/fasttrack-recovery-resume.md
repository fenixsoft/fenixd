<!-- knowledge: capability=fasttrack-recovery-resume rev=1 sources=spec/archive/2026-09-24-fix-fasttrack-recovery-resume-lane -->

# 快车道恢复续做

fast-track 派发入口与 implementer 分支同源消费 `_recovery_resume` 恢复标记，使 daemon 重启后 fast-track SPEC 同样在保留分支 worktree 内续做，而非被入口无条件清锚点后从零重做。

## 现行规则

- 入口消费（`core/pm_engine/dispatch/queue.py` fast-track 分支，判据与顺序逐条对齐 implementer 分支）：读 `state_machine.read_one(spec_name)`，仅当 `_recovery_resume` 为真时取 `branch` 为 `resume_branch`；`resume_branch` 非空时经 `wm.resolve_resume_site` 做载体三态解析（WT_AVAILABLE 原地 / WT_REBUILDABLE 从分支重建 / WT_UNAVAILABLE 降级），不自行拼装判定；无论解析结果如何都消费标记（写 `_recovery_resume: None`，一次性，防后续扫描反复尝试续做）；`resume_wt` 非空时经 `wm.mark_reused` 登记继承痕迹（携带恢复来源标记，供 prompt 注入）并打 INFO 说明在保留分支上续做。
- 降级留痕：`resume_branch` 非空但载体解析降级（`(None, None)`：分支不可解析/零提交/换壳失败）时打 WARNING（含 spec 名与分支名），随后按普通全新派发执行（此时可清空旧锚点）；`resume_branch` 为空（无标记的常规派发/标记在但 `branch` 为空）不打该 WARNING——该路径不是降级。
- 锚点清除排在续做判定之后，且仅在 `resume_wt is None` 时执行；派发入口不得无条件清除 `branch`/`implementer_run`（该清除会使 state_machine 为 fast-track spec 保全的锚点在派发当刻即被抹除）。
- 载体贯通：`run_fast_track` 接受 `pre_wt_path` 形参并透传至 `_execute_agent`（与 `run_implementer`/`run_repair` 同签名语义）；`pre_wt_path` 非 None 时不创建新 worktree，该路径进入跨 attempt 复用判定与终态收割登记；路径在 attempt 间隙被外部清理时改走新建分支路径，不以 `[Errno 2]` 秒挂一次重试额度。impl- 前缀 run_id、预算计数、成功路径 merge 语义不因此改变；缺省 `pre_wt_path=None` 时行为逐字节一致。
- prompt 继承注记：恢复续做命中的 `mark_reused` 携带恢复来源标记进入 `_active_reuse`；`_recovery_resume_note` 提供可选「要求恢复来源」判据（缺省关闭，implementer 分支既有调用保持不传、注入判据与文案不变）；fast-track 以该判据择一注入——命中恢复来源时注入恢复续做注记（框架保留已提交成果/从第一个未勾选项继续/不重做不回滚），否则退回既有 `_fast_track_reuse_note`（Worktree 继承注记）；未登记复用痕迹（`get_reuse_record` 返回 None）时返回空串零注入；两条语义重叠的「延续已有成果」段落不同时注入；普通重派轮（结果文件缺失/硬校验失败/零变更哨/transient 终态保留/跨 attempt 复用，复用痕迹无恢复来源标记）不误注「曾因 daemon 重启/停机被中断」的恢复归因。
- 派发出口锚点处置矩阵完备，不存在无条件抹除可续做锚点的出口：

| 出口 | 处置 |
|---|---|
| 首轮/常规派发（queue.py fast-track 分支） | 消费标记；仅未命中续做时清锚点 |
| 规模预检降级 full（fast_track.py） | 不清 `branch`/`implementer_run`；降级改写 mode 后重派 implementer，标记由其按分支消费 |
| 结果文件缺失 / 完成度判据 / 硬校验 / verdict 失败 / 零变更哨重派（fast_track.py） | 保留 `_recovery_resume` 语义，不新增清锚点 |
| transient 终态保留（runner.py fast-track 终态失败分支） | `keep_for_reuse` 保留现场，不清锚点 |
| repair lane fallback（repair_lane.py `_fallback_after_repair`） | 不清 `branch`/`implementer_run`（仅登记遗产供后继 run 收编）；`_repair_awaiting_remerge` 按既有语义清除；不消费 `_recovery_resume` |

- 两处清锚点出口以代码注释固定其与 `_recovery_resume` 的区分，避免被误当作同类缺口：engine.py 的 auto-recovery（stuck implementing，判据已确认无存活子进程，属「确认 run 已死」的有意重置）；rollback.py 的派发异常回滚（run 从未启动，标记尚未消费、锚点亦非本轮产出）。二者均不消费 `_recovery_resume`。
- 可观测：续做命中 INFO（spec 名、保留分支名、载体 worktree 路径）；载体解析降级 WARNING（spec 名、分支名与原因）；出口清锚点 INFO（含被清空旧锚点值，与 implementer 分支「新轮次派发清除旧锚点」同款）。日志须使「本轮是恢复续做还是从零重做」可直接判读，不以「新建了 worktree」这一间接下游信号推断。

## 溯源

- 2026-09-24 fix-fasttrack-recovery-resume-lane（spec/archive/2026-09-24-fix-fasttrack-recovery-resume-lane） — 新增 fast-track 恢复续做：入口同源消费标记、`pre_wt_path` 载体贯通、恢复来源判据注记择一注入、出口锚点处置矩阵与可观测留痕
