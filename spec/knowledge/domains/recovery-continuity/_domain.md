# 中断恢复与续做

中断恢复与续做域：覆盖 daemon 中断、停机与重启后的完整恢复链——现场保全、保留分支续做、存活核验、遗留处置、恢复监视告警、取消保持恢复与验证断点。

## 能力页

- [中断恢复保全与保留分支续做](interrupt-recovery-preserve.md) — 规划性排水、终止前保全、保留分支续做、清理协调与恢复期 re-merge-back
- [恢复分支锚点](recovery-branch-anchor.md) — 成功即落锚点、新轮次失效旧锚点与三层回落解析
- [恢复遗留状态检查](recovery-legacy-check.md) — 死亡 run 遗产保留、上下文注入与 agent 自主收编
- [恢复路径驱动证据与处置互斥](recovery-path-liveness.md) — admin run 不算驱动证据、verifier 重验与在飞处置互斥
- [恢复前存活核验与锁一致性](recovery-state-consistency.md) — 恢复动作前进程事实核验、worktree 锁重建回收与锁冲突退避
- [恢复监视升级前复查](recovery-watch-status-recheck.md) — 升级 dispatch_stalled 前重读状态与运行痕迹、顺延有界
- [恢复监视过渡窗口守卫](recovery-watch-transition-guard.md) — implementer→merge 过渡窗口内顺延 stale 判定
- [恢复后巡检与假就绪闭环复查](post-recovery-patrol.md) — auto-recovery 闭环复查、假就绪滞留巡检与指纹限频
- [取消保持 SPEC 的恢复运行动作](cancelled-spec-resume.md) — 界面一键恢复：复位 ready 按保留分支续做或降级重派
- [取消保持的持久化与恢复尊重](cancel-holdstate-durability.md) — `_cancelled_hold` 持久标记与恢复/监测豁免
- [快车道恢复续做](fasttrack-recovery-resume.md) — fast-track 入口同源消费恢复标记、载体贯通与出口锚点矩阵
- [验证断点续跑](verifier-checkpoint-resume.md) — verifier 重验从已完成场景之后继续
- [失败重试续跑](retry-resume.md) — 失败重试复用 worktree 与 session 从失败处续跑
