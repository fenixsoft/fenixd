# ADR-085：worktree 产物拷回统一收口，逐文件 mtime 守卫

date: 2026-09-14
status: accepted

## Context

agent 在 worktree 内以相对路径写入 per-spec 验证产物（`.fenix/verify-progress/<spec>/`）时，产物落在 worktree 真实目录内。runner 既有拷贝只覆盖根部 run-result → 主树共享文件一条路径，per-spec 目录无拷回机制，worktree 清理即销毁；共享文件随后被下一 spec 成功覆盖（读侧印章不符忽略），Dashboard 数据蒸发。产物保全不能依赖 agent 写入路径形态的自觉。

## Decision

- 拷回收口于 runner 成功收口点：与既有根部 result 拷贝同一 `if success:` 块内、worktree 清理之前。该块是 implementer / fast-track / repair / verifier 全部 worktree run 的成功必经点，一处收口覆盖全部 agent 类型；fast-track 延迟清理发生在 runner 返回之后，「拷回先于清理」时序天然满足。
- 拷贝语义 = 逐文件 `copy2` + mtime 三态守卫，不做整目录 replace：主树同路径缺失 → 拷入；worktree 版本较新 → 覆盖；主树版本较新 → 跳过（worktree 复用继承陈旧产物时，保护主树较新的冻结场景集、impl-result 等不被回灌）。copy2 保留源 mtime 使跨轮次比较稳定，嵌套子目录递归同处理。
- fail-open：单文件失败 WARNING 留痕（含 spec 名与源/目标路径）后继续，整体不抛出；无产物目录零动作零日志（正常形态 agent 全走主树绝对路径写入，避免噪音）。
- 失败路径（worktree_kept 保留给重派继承）不拷回——重派继承语义依赖 worktree 现场原样保留。

## Consequences

- 任何 agent 写入路径形态下 per-spec 产物不再随 worktree 清理丢失；verifier run 的新写产物同样受益，陈旧继承产物被 mtime 守卫挡住。
- mtime 不可靠文件系统的极端情况退化为「少拷一个文件」，与无拷回行为一致，无恶化。
- 逐文件 copy2 原子性弱于 `os.replace`：读侧 JSONDecodeError 兜底 + 写入发生在 run 收尾低频点，风险可忽略。
