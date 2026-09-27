# ADR-014：无人值守重试安全（指纹熔断 / 主树 stash / 单实例锁）

date: 2026-09-02
status: accepted

## Context

无人值守的自动重试一旦与不可自恢复的失败叠加即成为烧钱循环：主树脏导致 merge-back 必败 → spec 回 ready → 全新 worktree 全量重跑 → 再败，一次事故即烧穿预算。重试安全须从机制上区分「可恢复失败」与「同因重复失败」，并保护主树与 daemon 单例性。

## Decision

- 熔断以错误指纹判定而非纯计数：对错误文本归一化后取指纹哈希，同一指纹连续失败达到阈值（如 2 次）才置 `blocked`；不同根因的失败互不累计，网络抖动类可恢复失败不会被同因熔断误伤。
- 主树健康保护用 stash 而非强制 commit：派发前主树 `git status --porcelain` 非空时 `git stash push --include-untracked` 隔离，操作成功后 `stash pop` 还原；绝不把用户未完成的工作 commit 进历史。pop 冲突时保留 stash 条目 + WARNING，不阻塞状态流转。
- daemon 单实例用 flock 文件锁保证：启动时对专用锁文件获取排他 flock，失败即退出；flock 跨进程可靠且异常退出自动释放，无需清理逻辑。
- 配套运行卫生：单次 run 以 `--max-turns` 强制上界（CLI 不支持该参数时降级为不传并告警）；attempt 失败后复用同一 worktree + `--resume <session_id>` 续跑（implementer 车道），不整单重跑；孤儿 worktree 在启动时全量扫描清理；遥测噪音事件（thinking_tokens 等）在写盘前丢弃。

## Consequences

- 同因死循环在第二次失败即被熔断，代价上限为一至两次重跑而非无限；主树用户工作始终可从 stash 找回，不丢失也不入史。
- 指纹归一化对未见过的错误形态可能分桶错误——熔断可由人工解除，误熔断的代价小于漏熔断。
- stash 窗口期内主树处于暂存态，窗口内的并发构建/提交须感知该状态（冲突时以 stash list 为准恢复）。
