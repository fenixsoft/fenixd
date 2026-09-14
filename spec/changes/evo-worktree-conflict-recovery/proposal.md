# worktree-conflict-recovery — worktree 冲突恢复与降级诊断化

## 背景
add-web-ui 验证链中，08:46:41Z 新 planner-judge 因同一 spec 的活跃 worktree（08:31:30Z 由 planner-judge 1789115490 创建，09:26 才清理）被 dual-dispatch guard 拒绝，agent_runner 直接报「Failed to create worktree」后，pm_engine 无诊断地降级到旧版 verifier，最终经 legacy 路径误判 blocked（#3）。当前行为：创建失败即失败，无锁归属诊断、无安全清理重试、降级无原因字段。

## 目标
- worktree 创建失败时先诊断锁归属：锁由活动 run 持有 → 明确提示属并发（不回退）；锁为残留（孤儿/陈旧，daemon 重启后内存锁丢失但目录残留）→ 安全清理后重试一次。
- 禁止无诊断直接降级：降级动作必须携带原因字段与证据（锁归属、活跃 run id）。
- worktree 活跃记录含 run id/pid/创建时间，便于追溯残留来源。

## 非目标
- 不改 worktree 的并发保护语义（dual-dispatch guard 保留）。
- 不改 legacy verifier 读取路径（已在 verifier-result-single-source 覆盖）。

## 验收
- 残留 worktree 冲突时可自动清理并重试成功；活动 run 冲突时降级日志含原因字段。
- 同一窗口内不再出现「Failed to create worktree → 无诊断降级」的无痕路径。