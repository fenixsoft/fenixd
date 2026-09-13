# Proposal: fix-run-hang-amplification

## Why

`fix-root-init-import-shadow` 吞掉 **14.5 小时**（`total_duration: 52567s`，`_cost_usd: 10.27`）去交付一个**删一个 51 字节文件 + 加一个收集期守卫 + 一个回归测试**的改动。取证结论：交付物本身几分钟即完成，时间全部烧在一个**与本 change 无关的存量挂起**上，而框架的四条通道把这个挂起逐级放大成小时级浪费。

**事件链（全部可由 run jsonl 复盘）：**

1. **存量基线死循环**：09-11 `bb9de76c` 把内容完整性闸门接进 `dispatch.py` 双分支；`c6d5924c` 只给 `test_spec_scheduling.py` 补桩，**漏了 4 个文件**。空 tmpdir + 恒 ready 替身触发闸门 → 条目回队首 → `_process_queue` 死循环（调试栈落到 `admin_store._write_unlocked` 的 flock，**1593 次 fsync**，I/O 涨到 **44–60GB**）。
2. **挂起被误判为「推进」**：`_liveness_snapshot` 的 `events_in_window` 把**心跳事件**（`tool_progress`，每约 30s 一条）也计入「新事件」，使既有「窗口内零事件 → 直接判停滞」守卫恒久失效；判定 LLM 据此两次给出 `advancing`，两次续期各 1800s 全部发放。本案挂起 run 窗口内 **349 条心跳 vs 130 条实质结果**。**这是把挂起变成 10.5h 的直接原因。**
3. **超时重试给全新预算**：撞满 `9000s + 2×1800s = 12600s` 后被杀，重派的新 run 拿到**全新 12600s**，且不继承上一轮「套件在 32% 挂起」的诊断。三个 run 各撞满一次（3.36h + 3.41h + 3.37h ≈ 10.1h），共 6 个 impl run（正好用满 `impl_run_budget: 6`）。前 5 个都在「等它跑完」，只有最后一个换策略（faulthandler / strace / 基线 worktree 对照）才定性为存量挂起。
4. **并发套件争抢**：每个 run 窗口内都有 **3–8 个其他 Agent 在跑 `pytest`**（首窗口 95 次启动）。共享 CPU/磁盘/端口，`find_free_port` 的 TOCTOU 制造伪失败，把诊断带偏（首轮就误判为「并发端口竞争」）。

**四条通道相互叠加**，任一条单独存在都不会吃掉 14.5h。本 change 逐条治理，使「一个跑不动的 run」快速失败并降级，而不是烧穿全部预算再乘以重试次数。

**范围判定说明**：另有并行立项 `evo-add-fast-track-scale-precheck` 处理「三次超时」这一**症状**，其 proposal 归因为「任务面较大」。该归因被本次取证推翻——其实测对照样本自相矛盾：`fix-root-init-import-shadow` **12** 个任务 / 3× 超时，被当作「小 spec、单轮成功」的 `fix-dispatch-wakeup-gap` 反而是 **18** 个任务。本 change **不改动也不推翻** `evo-add-fast-track-scale-precheck`（规模分档与 extension 末位保全对真正的超大 spec 仍有价值），但 MUST 在 design 中显式声明：**该 spec 不覆盖本案根因**，避免误以为已治理。

## What Changes

- **挂起判别（点 1）**：①修正确定性缺陷——快照 MUST 把**心跳**（`tool_progress`）与**实质事件**（工具调用/结果/result）分离计数，「窗口内零事件 → 判停滞」的守卫只看实质事件，心跳 MUST NOT 作为 `advancing` 依据；②确定性短路**只保留「可观测零产出」**三条件同时成立的窄情形（阻塞等待超阈 + 关联输出文件可观测且零增长 + 窗口内工具完成数低于阈值），证据标注为启发式并记录输出文件与零增长区间；③**明确排除**「重复相同工具调用占比」「结果文本重复度」作判据（实测不判别，详见 design Context 表）。
- **存量阻塞显式归类（点 2）**：implementer 因「与本 change 无关的存量缺陷」无法通过全量回归时，框架 MUST 提供显式归类路径（存量阻塞），使该 run 快速收口为可判定的终态并保留证据，而非反复重跑全量套件至撞满超时。
- **重试预算与诊断连续性（点 3）**：同一 spec 的多次 attempt MUST 共享同一预算口径（累计墙钟/次数在 spec 级计入，重试不重置为满额）；重派的新 attempt MUST 继承上一轮的结构化诊断摘要（失败归因、已定性结论、已提交进度），随 prompt 注入，禁止从零重复探测。
- **并发套件资源隔离（点 4）**：全量套件执行 MUST 获得互不冲突的资源（端口段从进程/run 派生并可经环境变量覆盖），或经主机级互斥串行化；MUST 消除 `find_free_port` 的 TOCTOU 争抢伪失败。

## Capabilities

### New Capabilities
- `hang-discrimination`: 心跳与实质事件分离计数（修正守卫被心跳打穿的确定性缺陷）+ 停滞短路仅限「可观测零产出」窄情形
- `run-budget-continuity`: 同一 spec 的重试共享预算口径 + 新 attempt 继承上轮结构化诊断
- `baseline-blocked-gate`: 与本 change 无关的存量缺陷阻断全量回归时的显式归类与快速收口
- `concurrent-suite-isolation`: 并发套件的资源隔离/串行化，消除端口 TOCTOU 争抢

### Modified Capabilities
- `agent-run-timeout-supervision`（归档能力）：判定输入与判据增强（新增「无实质进展」维度），续期决策口径相应收紧；既有「次数与绝对上限双重封顶」「判定不可用失败安全」「可配置停用」语义不变。

## Impact

- **core/agent_runner/liveness.py**：`_liveness_snapshot` 分离计数实质事件/心跳并暴露工具完成数；「零事件」守卫改按实质事件判定；`_supervision_deadline_action` 增「可观测零产出」短路；`_judge_liveness` prompt 口径修订（心跳不构成进展）。
- **core/pm_engine/**（dispatch / budget 相关）：spec 级预算口径、重试诊断继承注入点。
- **core/agent_runner/runner.py**：重派 attempt 的 prompt 上下文注入；超时收口路径与存量阻塞归类对接。
- **测试与验证资源**：端口分配来源（`find_free_port` / `FENIX_VERIFY_PORT` 相关）与并发互斥。
- **tests/**：挂起判别的确定性单测（构造重复工具调用序列）、预算连续性断言、存量阻塞归类断言、并发端口隔离断言。
- 无 dashboard UI、无新增配置键（阈值用既有 config 派生常量，design 固化）。
