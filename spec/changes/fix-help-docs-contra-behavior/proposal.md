## Why

2026-09-26 的 docs/help 与代码现状偏差审计定案：docs/help 帮助文档（主体写于 09-21~09-25）存在 11 类「描述与现行为相反」的 P0 级偏差。这些偏差会直接误导运维处置——例如按文档「回归失败重试一次后 worktree 保留待人工」去等人工释放，而代码实际已自动定向重试 3 轮并现场即弃；按文档「严格优先级串行调度」误判并发行为；按文档「1800 秒硬超时」误判架构图生成故障。本 SPEC 只做「把说错的改对」，不新增机制描述（缺失机制的补齐由 add-help-docs-mechanism-coverage 承载）。

## What Changes

- 修正 `05-verification.md`：verdict 四分类中 blocked-env / inconclusive 的流向描述（现为两级豁免握手 + inconclusive 自动重验链 ≤3 轮后停等人工，非「回 testing 重派 / 人工检查」）；验证流水线出题时机（已前置 ready 态与实现并行，非 implemented 后串行）；冻结场景集变更通道（两条 → 三条，新增契约版本迁移自动通道）。
- 修正 `06-governance.md`：调度模型「严格优先级、不同优先级不并行」→ 宽松优先级并行（无更重要活动任务即可派发、不抢占、队列老化）；`agents.max_concurrent` 缺省 2 → 5。
- 修正 `07-safeguards.md`：autostash 回收「冲突时自动解决（UU → add）」→ 三分诊（三方重试 → 恢复 commit → 兜底登记，绝不静默丢弃）；「十状态生命周期」→ 11 状态。
- 修正 `08-dashboard.md`：impl 收尾代码审查「实现者写结果文件前内联调用、并发经提示词软约束」→ 框架侧异步并行车道（merge-back+tester 派发时点启动、并发硬生效缺省 4）；架构图「1800 秒硬超时整组击杀」→ 两段式（探索 ≤720s / 出图 ≤1080s 分段击杀 + HEAD 指纹一致跳过探索段）。
- 修正 `09-config.md`：`agents.max_concurrent` 缺省 5；`admin.code_review_fix` 回归失败处置段整段重写（定向重试 ≤`targeted_retry_max` 缺省 3 轮只重跑失败子集、耗尽现场即弃入档案、FAIL_RETRY_MAX=3 预算内新链自动重试，删除「保留待人工 / release_failed_batch」旧世界描述）；回归「跑全量」→ 首轮全量+定向轮子集；「30 分钟 full scan 兜底」→ `schedule.poll_interval_minutes`（缺省 30）；`admin.shutdown_drain_seconds` 双侧行为补规划性重启豁免（restart_request 在场时按 `agents.run_drain_max_seconds` 排水不被 0 夹紧）；`impl_code_review_concurrency` 缺省 4 且硬生效；`agents.models` 角色集 10 → 11（+code-fix）；审查产物「agent 逐文件落 out-<run_id>.jsonl」→ 分片直写 out-<run_id>-b<N>.jsonl 聚合。
- 修正 `README.md`（03 行「10 状态全景」→ 11 状态）、`02-concepts.md`（「十一类 Agent」→ 12 类 +code-fix 行）、`03-lifecycle.md` 与 `12-faq.md`（hook 事件「十状态枚举」→ 11 状态 + `all-done` 伪事件）。

## Capabilities

### New Capabilities
- `help-docs-contra-behavior-fix`: 帮助文档 P0 反偏差修正——docs/help 各章中「描述与现行为相反」的断言逐条改写为与代码一致（verdict 豁免握手流向、宽松优先级调度、autostash 三分诊、ocr 并行车道、两段式架构图超时、code_review_fix 失败处置、排水豁免、状态/角色/并发缺省口径、hook 事件枚举、分片直写产物形态）。

### Modified Capabilities

## Impact

- 仅改动 `docs/help/*.md`（05/06/07/08/09/README/02/03/12 共 9 份），零代码改动、零配置改动、零运行时行为变化。
- 帮助页（Dashboard /help）直接渲染该目录，改完即对用户可见；无需 daemon 重启（文档由前端按需拉取）。
