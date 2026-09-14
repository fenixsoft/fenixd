# 设计 — worktree-conflict-recovery

## 活跃记录扩展
- worktree_manager 的锁记录从内存 _spec_locks 扩展为磁盘 sidecar（.fenix/runs 或 .fenix/worktree-locks.json）：lock_key=spec:agent_type → {run_id, pid, created_at}。
- daemon 重启后锁记录保留，供诊断读取；残留判定：pid 不存在 或 run 转录缺失 或 created_at 超过阈值。

## 恢复流程
- create worktree 失败（already active）时：
  1. 读锁记录；
  2. 活动判定（pid 存活）→ reason=parallel-run，直接按现有 dual-dispatch guard 语义处理（不重试）；
  3. 残留判定 → 展示清理意图（git worktree list 核对目录），git worktree remove 后重试一次创建；
  4. 重试失败 → 降级，reason=stale-recovery-failed。

## 降级日志
- pm_engine 降级分支统一走 emit 函数：level=WARNING，字段含 reason、spec、活跃 run_id、worktree 路径；dashboard signal 一并携带。

## 改动点
- .fenix/core/worktree_manager.py：锁记录持久化 + 残留判定 + 清理重试。
- .fenix/core/agent_runner/runner.py：降级调用传递 reason。
- .fenix/core/pm_engine/verification.py：降级日志诊断字段。