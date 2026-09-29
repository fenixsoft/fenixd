<!-- knowledge: capability=agent-shutdown-interrupt rev=2 sources=spec/archive/2026-09-02-fix-graceful-shutdown-agents,spec/archive/2026-09-19-fix-recovery-branch-anchor-without-worktree -->

# Agent 优雅中断与停机协议

daemon 关停时对在跑 agent 的终止协议，以及停机路径对在飞成果（run 标记、分支、worktree）的保护。

## 现行规则

- 主动终止：daemon 收到关闭信号（SIGTERM/SIGINT）进入优雅退出时，对所有未完成的在跑 agent 子进程主动发起 SIGTERM，不等待 agent 自行完成（无逐 agent 300s 等待窗口）；整体终止阶段在 10s 量级内完成，确保 daemon 在 supervisor 的 60s SIGKILL 窗口内退出。已完成的 run 不产生 interrupted 标记。
- 缓冲与强杀兜底：SIGTERM 后提供 ≤10s 优雅缓冲；窗口结束仍未退出者被 SIGKILL 强制终止，interrupted 标记不依赖 agent 是否优雅退出（先行写入）。
- 并行终止：多个在跑 agent 时一次性对全部发起 SIGTERM 与标记写入（非串行逐个等待），总时长不随 agent 数量线性增长。
- interrupted 标记：被框架终止的 run 在 run 文件写入 `{"type": "interrupted", "reason": "daemon shutdown", "by": "agent_runner"}`（含原因），使恢复链与失败归因可区分「框架主动终止」与「agent 自身失败」。写入时机早于或等于保全动作（sidecar 落盘）。适用对象限定为尾部无终态事件的 run（与 `sweep_runs_without_terminal_state` 同判据）——对已含 `result` 终态的自完成 run 追加会注入第二个终态事件、污染失败归因，禁止如此；排水窗口内已自行退出、后置收口未落盘的 run 由 spec 级「待 re-merge-back」标记与保全 sidecar 承载，不依赖本标记识别。
- 关闭期分支保护：`cleanup_stale_worktrees` 执行 `git branch -D` 前检查分支引用——分支名等于 STATE 中任一 `implementing` / `implemented` / `testing` spec 的 `branch` 字段值、或任一带 `_recovery_resume` 标记 spec 的 `branch` 值（恢复保留续做后的 `ready` 形态同样受保护）、或按「完整 spec 名 + 分隔符边界」全等比较（口径同 recovery-branch-anchor：去掉 `<prefix>/` 后末段为纯数字时间戳、前段与 spec 名全等）匹配任一在飞实现分支时，保留该分支（可照常删除 worktree 目录）。判定不用 `<prefix>/<spec>-*` 前缀 glob（spec 名互为前缀会误归属）。保留与删除均记日志，保留打 WARNING 含 spec 名与分支名。
- 关闭期保护集结构性下界：停机路径构造 orphan 清理保护集不得存在「空集 → 无差别清理」退化路径——保护集至少包含 STATE 中所有 `implementing` spec 经事实查询解析出的在册 worktree 路径，由状态而非事件可见性决定（排水窗口内 agent 自行退出、sidecar 未写不等于收口完成）。同一 spec 的多个在册载体（如 impl- 与 repair- 并存）全部受保护，不因单值事实查询对歧义返回 None 而漏保护。清理确有发生时，日志记录保护集各来源的条目数；STATE 中全然无在飞 spec 且 sidecar 无在册项时保护集为空，按现行行为正常清理。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：agent 关闭语义为 terminate 流程，先终止子进程再收尾；以 interrupted 标记识别被打断的 run，恢复链路据此区分打断与失败
- [2026-09-02 fix-graceful-shutdown-agents](spec/archive/2026-09-02-fix-graceful-shutdown-agents/) — 固化优雅退出主动 SIGTERM 与 10s 量级终止、缓冲超时 SIGKILL 兜底、多 agent 并行终止与 interrupted 标记追加
- [2026-09-19 fix-recovery-branch-anchor-without-worktree](spec/archive/2026-09-19-fix-recovery-branch-anchor-without-worktree/) — interrupted 标记收窄为尾部无终态 run 且写入时机先于保全；增设关闭期分支在飞引用保护（全等比较口径）与停机保护集结构性下界
