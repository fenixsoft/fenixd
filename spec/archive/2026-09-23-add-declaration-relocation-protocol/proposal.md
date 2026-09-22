# Proposal: add-declaration-relocation-protocol

## Why

交付物守卫读的是**主树** `spec/changes/<spec>/tasks.md` 的声明段，而实现 Agent 只能改
**分支/worktree** 内的那份；两者错层。当规划期声明的路径被后续重构删除/改名（上游演进，
非本 spec 所为），主树声明即陈旧且永不满足 → 守卫每轮判 `missing` → 打回重派 → 复用同分支
→ 原地打转直至 `blocked`，烧掉整轮预算与全部既有成果。

09-18 `fix-relint-redispatch-legacy` 实证：`core/pm_engine/dispatch.py` 已被
`refactor-giant-classes`(6491c960) 拆为 `dispatch/` 包并删除，但该 spec 主树声明仍指向
单文件；实现 Agent 已在分支 `814f64f5` 把声明对齐为 6 条真实路径（验证 5/5 全过），
守卫仍读主树旧声明，两轮重派原地空转（`_retry_count` 2/3）。人工回填主树声明方才解卡——
根因未除，同类触发条件（声明路径被重构失效 + 该 spec 未 merge-back）必然复发。

这不是单点 bug，是**声明权威源**与**声明改写权限**分离造成的结构性错层：声明由规划期
在**主树**写入，实现期只能在**分支**改写，而所有消费方（守卫、预分类、裁决、提示词组装、
fast-track 快照）各自硬编码主树读取，无统一的解析契约，也无「声明路径失效」这一确定性
信号的处置通路。

## What Changes

- **统一声明解析契约（单一权威源）**：新增解析器，所有消费方经它取「某 spec 在当下适用的
  声明集合」，杜绝各点各自拼主树路径。解析分层：**分支/worktree 版本优先**（实现期真实
  在测的那份），缺失回退主树（向后兼容、无分支场景安全）。
- **收缩防护（防绕门）**：声明只可增不可减。以派发时的**可信基线快照**（实现 Agent 不可
  触及）为参照，凡基线路径在生效声明中被**无声剔除**（既不在分支满足、也无合法重定位
  凭据）→ 判违规，阻断「删声明行即绕守卫」。
- **声明重定位协议**：定义「规划期声明路径因上游重构失效」的正式语义与机械执行——
  确定性信号（`new`/`modify` 路径在主树 HEAD 已不存在 = 基线陈旧，分支上永不可满足）
  → 重定位（旧路径缺 + 新路径在分支存在 + 凭据在册）→ 改写生效声明 + 审计留痕，
  而非打回重派。
- **双车道裁决流水线统一**：full 车道的 dispute-judge 终审 / 机械裁决 / 重定位前置分类，
  下沉为车道无关的统一流水线；fast-track 车道接入同源处置（当前它无终审兜底，直落
  重派）。
- **审计与回滚语义**：重定位与软化统一落 dispute 审计流（含 before/after 全文、触发 run、
  凭据来源），可追溯、可复核、可回滚。

## Capabilities

### New Capabilities

- `deliverable-declaration-resolution`: 统一声明解析契约——分层解析（分支/worktree 优先、
  主树回退）、可信基线快照、收缩防护判定、供全部消费方共用的单一权威源 API。
- `declaration-relocation-protocol`: 声明重定位协议——「规划路径因上游重构失效」的确定性
  信号、凭据契约（旧路径缺 + 新路径在 + 来源）、机械改写与审计留痕、失败安全回退。

### Modified Capabilities

- `implementer-deliverable-gate`: 守卫由「硬编码主树读取」改为经统一解析器取生效声明；
  新增陈日声明前置分类（确定性信号 → 重定位通道，不打回）。
- `deliverable-declaration-triage`: 缺件终审/机械裁决/预分类由 full 专属下沉为车道无关
  流水线，fast-track 车道接入同源处置。

## Impact

- **核心门禁链路**：`core/pm_engine/verification/branch_guard.py`（`_deliverable_gate_missing`
  及零变更/relint 相邻逻辑）、`core/pm_engine/dispatch/{queue,fast_track,adjudication}.py`
  （双车道守卫调用点与裁决流水线）、`core/pm_engine/engine.py` 门面委托表。
- **声明解析层**：`core/deliverables.py`（提取/软化/重定位 API 扩展）、`core/fast_track_result.py`
  （fast-track 快照读取同源化）、`core/agent_runner/prompt_builder.py`（提示词组装同源化）。
- **状态/审计**：`.fenix/verify-progress/<spec>/` 新增可信基线快照文件；dispute 审计流
  记录形态扩展（重定位条目）。
- **回归面**：双车道收口路径、存量无声明段 spec 的回退语义、`delete`/`reference` kind 的
  既有反判与软化语义、并发编辑（spec-review）场景。
- **风险**：读取分支声明引入「实现方自证」张力，必须由收缩防护 + 可信基线快照闭合，
  否则等价于把守卫交给被守卫者。此为本次设计的核心安全边界。
