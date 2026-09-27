# ADR-054：merge-back 语义冲突原地修复——分支侧合 main，主树恒不冻结

date: 2026-09-09
status: accepted

## Context

merge-back 的产物类冲突已有目录层次容错化自愈兜底，语义冲突失败是剩余最大浪费点：自愈不适用时 abort 主树、spec 置 ready 全新重派 implementer，实测一次重派报废 3.5h 实现工作。

## Decision

- 分层：worktree_manager 保持纯 git 操作层，失败时返回结构化冲突分类（冲突路径清单 + 是否仍有语义冲突）；是否进入修复、派发与轮次计数由调度层决策——git 层不派 agent，与「能治则治、不能治交回上层」的既有边界一致。
- 修复方向反转：repair agent 在实现分支一侧执行 `git merge main` 并解决冲突，而非在主树合分支。主树在派发前已 abort 保持干净，repair 期间不冻结其他 spec 推进主树；repair commit 后重推 merge-back（分支已含 main 历史，自然快进）；再遇新冲突按既有重试/熔断路径收敛。
- 分支载体三态以 git 事实（worktree list + 分支解析）为判定基准，不信任内存表（daemon 重启即失）：worktree 在且解析到实现分支 → 原地进入；目录不在但分支在 → 换壳 checkout 既有分支；分支不在 → fallback 全新重派并注入当次失败上下文。
- repair run 复用遗留现场认领语义（认领即摘出清扫登记，宽限期不回收），并注册 spec 锁防修复中重复派发；轮次上限为模块常量（2），不新增配置键；merge 失败熔断指纹计数不被 repair 轮清零，连续失败照常累计。

## Consequences

- 「必然的重做」变为「可失败的努力」：repair 解不了必须显式失败，不自证——最终正确性由 verify 链把关（与 ADR-034 的原地修复哲学同族，但触发域是 merge 冲突而非验证缺陷）。
- 主树不冻结的代价是 repair 期间主树前进可能带来 re-merge-back 新冲突，真实并发窗口小，按既有重试与熔断收敛。
