# 设计：fix-run-hang-amplification

## Context

`fix-root-init-import-shadow` 用 14.5h / $10.27 交付一个可分钟级完成的改动。取证（run jsonl + 源码）确认四条通道叠加放大一个**与本 change 无关的存量挂起**：

1. **存量死循环**：09-11 `bb9de76c` 内容闸门接进 `dispatch.py` 双分支，`c6d5924c` 只补 `test_spec_scheduling.py` 漏 4 文件 → 空 tmpdir 触发闸门 → 条目回队首 → `_process_queue` 死循环（`admin_store._write_unlocked` flock，1593 fsync，44–60GB I/O）。
2. **挂起被判 advancing**：`_liveness_snapshot`（`core/agent_runner/liveness.py:320`）只有 `events_in_window` / `tool_use` / `tool_counts`（仅工具名）/ `last_event_age` / `last_output`；死循环持续产事件与 I/O 并持续写入**心跳**，`_judge_liveness`（`liveness.py:420`）两次判 `advancing`，`max_extensions=2` 的 3600s 续期全额发放。
3. **重试给全新预算**：撞满 `9000 + 2×1800 = 12600s` 被杀后，`dispatch.py:1091` 因 `impl_status is None`（超时杀无 `.fenix-run-result.json`）触发 `_exempt_dead_run_budget`（`core/pm_engine/budget.py:117`）**回退预算计数** → 预算刹车失效；`dispatch.py:1136-1149` 在 `max_retries` 耗尽时把 `_retry_count` 归零并重新入队 → 重派不耗预算、无上限。且跨 attempt **无结构化诊断继承**——唯一通道是 STATE `error` 文本（`core/agent_runner/prompt_builder.py:487 _prev_error_section`），异常回滚路径还会把它清掉（`dispatch.py:1300`）。
4. **并发争抢**：本案每个 run 窗口内有 3–8 个其他 Agent 跑 `pytest`；`core/proc_utils.py:32 find_free_port()` **先 bind 再 close**（TOCTOU），并发下产生伪失败。

**架构事实（来自源码探索，纠正提案阶段的假设）：**
- 框架**没有**机械的「全量套件全绿」硬门。收工门只校验提交（`runner.py:1818`）与交付物文件存在性（`verification.py:2621`）；「全量测试全绿」是 planner 写进 spec 自身 `tasks.md` 的任务（本案 5.1）加 implementer 提示词的软要求（`agents/implementer.md:6`）。
- 框架**没有**「存量基线失败」概念（`baseline` 仅指视觉截图与存活计时基线）。
- 多 worktree 并发跑测试**无任何**互斥/串行/资源隔离。
- worktree 缺 `.fenix/hooks/*`（gitignored 自举物），`tests/test_block_main_tree_write_hook.py` 与 `tests/test_planner_scenarios_batching_hook.py` 硬依赖该路径：前者失败、后者 `raise AssertionError`。

**挂起判别的实测取证（本 change 的设计依据，全部由 run jsonl 复算）——推翻了「重复调用占比」判据：**

| 判据 | 挂起 run（4 个） | 合法长跑 run | 结论 |
|---|---|---|---|
| 相同工具调用占比（全程） | 0.06 / 0.07 / 0.08 / 0.13 | 全场最高 0.17 | 阈值 0.75 **永不触发**；下调到能触发即误杀合法 run |
| 相同口径（600s 窗口 + ≥12 样本） | 0.08 | 最高 0.17 | 同上 |
| 工具**结果**重复度 | 0.15 / 0.17 / 0.21 | 0.20 / 0.24 / 0.18 | **反向**：合法 run 更高 |
| 窗口内 心跳/结果 比 | 6.33 / 6.33 / 6.67 | 6.33 / 6.33 / 6.33 | 完全相同，不判别 |
| 全程吞吐 tools/h | **23–39** | **67–155** | 有判别力，但只能事后统计，且混淆「合法慢」与「挂起」 |
| 后台调用**输出文件零增长** | 0–22 字节（轮询数小时） | — | 唯一真正反映子进程挂起的可观测信号 |

**根本原因（方法论结论）**：本案死循环发生在 **pytest 子进程**内部（`_process_queue`），**不在 Agent 的工具调用里**。Agent 本人一直在做多样且合理的诊断工作，转录看起来完全正常——因此任何**纯转录**的挂起启发式都有天花板。判据若不能观测「被等待的子进程」，就分不清「挂起」与「合法慢」。

## Goals / Non-Goals

- **Goals**：让「跑不动的 run」快速失败并降级而不是烧穿预算 × 重试次数；修正让 judge 误判 `advancing` 的**确定性缺陷**；让存量阻塞与本 change 回归可区分；让并发套件不产生伪失败。
- **Non-Goals**：
  - **不做纯转录的挂起启发式主防线**：转录看不到子进程挂起（上文方法论结论）。挂起检测 MUST 以「可观测零产出」为限，主防线是**有界执行**（D3）——不让 Agent 无限期等待不受控的子进程。
  - **不修 `.fenix/hooks` 在 worktree 的部署机制**——只让依赖测试在缺失时 skip。
  - **不改动也不推翻 `evo-add-fast-track-scale-precheck`**：并行 evo spec 用「tasks.md 任务数」做规模分档并做 extension 末位保全，对真正超大 spec 仍有价值。**但 MUST 明确该 spec 不覆盖本案根因**——其对照样本自相矛盾（本案 12 任务 3× 超时，被其当作「小 spec、单轮成功」的 `fix-dispatch-wakeup-gap` 是 18 任务），且对无限挂起「给更多预算」是反向伤害。边界：evo 管**预算档位**，本 change 管**挂起识别与重试刹车**。
  - 不引入 LLM 规模预估，不新增配置键（阈值用常量固化）。

## Decisions

### D1：修正「心跳被当作进展」的确定性缺陷；挂起短路只保留「可观测零产出」

**选择 A（确定性缺陷修复，必做）**：`_liveness_snapshot` MUST 分离计数 **实质事件**（`assistant` / 带 tool_result 的 `user` / `result`）与**心跳**（`tool_progress`）；`events_in_window` 的进度语义 MUST 只取实质事件。当前口径下令心跳（无时间戳，按文件 mtime 在窗口内即计入）持续刷新 `events_in_window`，使既有「窗口内零事件 → 直接判停滞」守卫**恒久失效**，并让 judge 看到「事件在流动」。

**选择 B（短路条件收紧）**：确定性短路 MUST 只在**可观测零产出**三条件同时成立时触发：①窗口内阻塞等待的后台调用时长超阈；②其 `output_file` 可观测且大小零增长；③窗口内工具完成数低于阈值。任一不成立（尤其输出文件不可观测）→ 走既有 LLM 判定。短路证据 MUST 标注为启发式「零产出」判定，含输出文件路径与零增长区间。

**选择 C（明确排除的判据）**：MUST NOT 使用「重复相同工具调用占比」或「结果文本重复度」作为停滞判据——实测不判别（见 Context 表），且下调阈值将误杀合法 run。

**常量与依据（固化于 liveness.py 常量区，注释标注）**：
- `HANG_BLOCKED_CALL_SECONDS = 300`：单个后台调用被阻塞等待的时长阈值。
- `HANG_ZERO_GROWTH_WINDOW_SECONDS = 300`：输出文件零增长需持续的窗口。
- `HANG_MIN_TOOL_COMPLETIONS = 3`：窗口内工具完成数下限（低于此视为无进展）。

**为什么把重心从「检测」移到「有界」**：pure-transcript 检测有天花板（Context 方法论结论）。真正可确定的是**不让 Agent 去无限期等待**——D3 的有界入口能在数分钟内直接报出「挂在 `test_dispatch_aging`」，与 Agent 行为无关。

### D2：预算刹车按终态细分豁免 + 结构化诊断继承

**选择 A（预算）**：`_exempt_dead_run_budget`（`budget.py:117`）的调用判据细化——豁免**仅适用于基础设施性死亡**：run 终态为 `interrupted`（daemon 关闭/重启连带杀）或归因指向网关链路耗尽；**监督超时/被判停滞而杀**（终态 `error` 且 reason 含 `Timeout after ... extension budget exhausted` 或 `stagnant`）**不豁免**——它确实消耗了整份预算。

**理由**：既有豁免的立论（`fix-budget-counting-semantics`：故障密集日网关死亡烧预算）针对**没跑满预算就死**的 run；本案是**跑满并超支**的 run，成本语义相反。用同一豁免退掉后者计数，等于拆掉唯一的刹车。

**选择 B（诊断继承）**：新增 spec 级结构化诊断字段（如 `_impl_diagnosis`），run 终结时写入（终态类型 + 归因 + 已定性结论 + 已提交进度：分支与已勾选任务）；`_prev_error_section`（`prompt_builder.py:487`）扩展为在 error 文本之外注入该结构化段。`_rollback_failed_dispatch`（`dispatch.py:1261-1311`）清 `error` 时 MUST NOT 清掉诊断字段。

**理由**：本案前 5 个 attempt 全部重复探测「套件是否真挂起」，只有最后一个换了策略（faulthandler / strace / 基线对照）。若第二轮就继承「已定性：存量挂起」，可省大部分时间。

### D3：有界全量套件入口 + 存量归类 + worktree 自举物 skip

**选择**：新增 `bin/run_full_suite.py` 作为**有界全量套件入口**：硬超时运行 `pytest tests/ -q`，启用 faulthandler（`-p faulthandler --faulthandler-timeout=<N>`）以在挂起时打印栈；超时/挂起时中止并输出**挂起测试标识**。附 `--baseline <ref>` 模式：在变更前基线的临时 worktree 中跑同一套件，输出两侧失败集合差异，直接给出「存量 / 本次引入」归类。
- 入口路径仅存在于主树（`bin/` 入库），worktree 经 `.fenix/bin` 符号链接可达。
- `agents/implementer.md` 与 `core/agent_runner/prompt_builder.py` 的 implementer/repair 契约段补：全量回归 MUST 走有界入口（或等价带超时方式），MUST NOT 裸调 `pytest tests/ -q` 无限等待。
- **worktree 自举物 skip**：两个 hooks 依赖测试对 `.fenix/hooks/*` 缺失改为 skip（`pytest.mark.skipif` 等价），skip 原因指明「自举物未部署（worktree 预期形态）」；主树存在时断言行为不变。

**为什么落在 `bin/`**：agent 通过 Bash 跑套件，框架无法拦截其任意命令；提供一个确定性、可复现的入口并写进契约，是最小可行且可测的收口方式。

### D4：端口分配去 TOCTOU + 套件并发隔离手段

**选择**：`core/proc_utils.py:32 find_free_port()` 改为不做「探测即释放」——提供保留已绑定 socket 的分配路径（contextmanager 等价），保留既有返回 int 的 API 兼容包装并在绑定失败时重试。新增按 run/worktree 派生端口段的环境变量约定（如 `FENIX_SUITE_PORT_BASE`）；`FENIX_VERIFY_PORT` 语义不变。并发隔离手段：`bin/run_full_suite.py` 加主机级互斥（沿用 `.fenix/` fcntl 文件锁范式），同一主机全量套件串行；锁获取结果写日志供复盘。

## Risks / Trade-offs

- **[零产出短路误判合法慢]** 块缓冲的合法 pytest 同样长时间零输出。缓解：三条件同时成立才短路（含「阻塞等待时长」与「工具完成数」两个正交条件）；证据标注为启发式；误杀后果有重试兜底，且远优于 10.5h 空转。
- **[预算豁免细分误伤真实网关死亡]** 判据按终态事件类型（`interrupted` vs `error`+timeout reason）区分；网关链路耗尽的归因文案需一并纳入豁免白名单，以 `fix-budget-counting-semantics` 既有归因字符串为准。
- **[有界入口不被 agent 采用]** 单靠新增脚本无强制力。缓解：契约段显式引导；后续可加机械告警（检测裸 `pytest tests/` 长跑）。
- **[worktree skip 掩盖真实回归]** 若某 change 恰要改 hooks 测试本身，skip 会遮蔽。缓解：skip 原因显式；主树执行路径不变。
- **[并发串行降低吞吐]** 权衡：排队成本远低于伪失败导致的误诊与重跑；端口段隔离优先于互斥。
