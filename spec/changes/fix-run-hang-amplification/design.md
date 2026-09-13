# 设计：fix-run-hang-amplification

## Context

`fix-root-init-import-shadow` 用 14.5h / $10.27 交付一个可分钟级完成的改动。取证（run jsonl + 源码）确认四条通道叠加放大一个**与本 change 无关的存量挂起**：

1. **存量死循环**：09-11 `bb9de76c` 内容闸门接进 `dispatch.py` 双分支，`c6d5924c` 只补 `test_spec_scheduling.py` 漏 4 文件 → 空 tmpdir 触发闸门 → 条目回队首 → `_process_queue` 死循环（`admin_store._write_unlocked` flock，1593 fsync，44–60GB I/O）。
2. **挂起被判 advancing**：`_liveness_snapshot`（`core/agent_runner/liveness.py:320`）只有 `events_in_window` / `tool_use` / `tool_counts`（仅工具名）/ `last_event_age` / `last_output`，**无「是否重复相同操作」维度**；死循环持续产事件与 I/O，`_judge_liveness`（`liveness.py:420`）两次判 `advancing`，`max_extensions=2` 的 3600s 续期全额发放。
3. **重试给全新预算**：撞满 `9000 + 2×1800 = 12600s` 被杀后，`dispatch.py:1091` 因 `impl_status is None`（超时杀无 `.fenix-run-result.json`）触发 `_exempt_dead_run_budget`（`core/pm_engine/budget.py:117`）**回退预算计数** → 预算刹车失效；`dispatch.py:1136-1149` 在 `max_retries` 耗尽时把 `_retry_count` 归零并重新入队 → 重派不耗预算、无上限。且跨 attempt **无结构化诊断继承**——唯一通道是 STATE `error` 文本（`core/agent_runner/prompt_builder.py:487 _prev_error_section`），异常回滚路径还会把它清掉（`dispatch.py:1300`）。
4. **并发争抢**：本案每个 run 窗口内有 3–8 个其他 Agent 跑 `pytest`；`core/proc_utils.py:32 find_free_port()` **先 bind 再 close**（TOCTOU），并发下产生伪失败。

**架构事实（影响设计，来自源码探索，纠正提案阶段的假设）：**
- 框架**没有**机械的「全量套件全绿」硬门。收工门只校验提交（`runner.py:1818 _check_terminal_no_commit_gate`）与交付物文件存在性（`verification.py:2621`）；「全量测试全绿」是 planner 写进 spec 自身 `tasks.md` 的任务（本案 5.1）加 implementer 提示词的软要求（`agents/implementer.md:6`）。
- 框架**没有**「存量基线失败」概念（`baseline` 仅指视觉截图与存活计时基线）。
- 多 worktree 并发跑测试**无任何**互斥/串行/资源隔离。
- worktree 缺 `.fenix/hooks/*`（gitignored 自举物），`tests/test_block_main_tree_write_hook.py` 与 `tests/test_planner_scenarios_batching_hook.py` 硬依赖该路径：前者失败、后者 `raise AssertionError`。

## Goals / Non-Goals

- **Goals**：把「跑不动的 run」从「烧穿全部预算 × 重试次数」压缩为「快速失败并降级」；让挂起在数分钟内被确定性识别；让存量阻塞与本 change 回归可区分；让并发套件不产生伪失败。
- **Non-Goals**：
  - **不修 `.fenix/hooks` 自举物在 worktree 的部署机制**——本 change 只让依赖测试在缺失时 skip（部署另议）。
  - **不改动也不推翻 `evo-add-fast-track-scale-precheck`**：并行立项的 evo spec 用「tasks.md 任务数」做规模分档并做 extension 末位保全，对真正超大 spec 仍有价值。**但 MUST 明确：该 spec 不覆盖本案根因**——其对照样本自相矛盾（本案 12 任务 3× 超时，被其当作「小 spec、单轮成功」的 `fix-dispatch-wakeup-gap` 是 18 任务），且对无限挂起「给更多预算」是反向伤害。两 spec 边界：evo 管**预算档位**，本 change 管**挂起识别与重试刹车**。
  - 不引入 LLM 规模预估，不新增配置键（阈值用常量固化）。

## Decisions

### D1：挂起判别用「重复相似操作占比」做确定性短路，进 LLM 前拦截

**选择**：在 `_liveness_snapshot`（`liveness.py:320`）增加工具调用指纹聚类——指纹 = `工具名 + 规范化入参`（`json.dumps(输入, sort_keys=True)`）；产出 `repeat_ratio`（最大同指纹簇占窗口内工具调用数比例）与 `top_fingerprint`。在 `_supervision_deadline_action`（`liveness.py:541`）决策矩阵中，于步骤 4（judge_window 内零事件）之后、步骤 5（LLM 判定）之前插入 **4.5 确定性短路**：采样数 ≥ `HANG_MIN_TOOL_CALLS` 且 `repeat_ratio ≥ HANG_REPEAT_RATIO_THRESHOLD` → 直接 `kill`（reason `stagnant: repeated identical tool calls`），不发起 judge LLM。

**常量与样本依据（固化于 liveness.py 常量区，注释标注）**：
- `HANG_REPEAT_RATIO_THRESHOLD = 0.75`：本案 d1-a1 窗口内 `TaskOutput {"task_id":"beqdmo0dh","block":true,"timeout":600}` 一类同参数轮询反复出现（该 run 共 17 次 TaskOutput、349 条 heartbeat），同指纹占比远超阈值；而正常推进的 run 工具调用天然多样。
- `HANG_MIN_TOOL_CALLS = 12`：样本下限，防小窗口（如只 3 次调用）偶发重复被误判。

**为什么用确定性短路而非只改 LLM prompt**：LLM 判定有成本、有延迟、且本案实证它会看「事件在增长」就判 advancing。确定性短路对**最典型的挂起形态（同参数轮询死循环）**零延迟、零成本、可单测。LLM 路径保留给「非重复型停滞」（如多样化但无产出）。

**后台子进程零产出**：作为**证据**纳入快照（`background_stall`：窗口内出现 `task_started`/`TaskOutput` 且其 `output_file` 大小在监督器记忆的两次采样间零增长），参与 LLM 判定，但**不**做确定性短路（需要跨采样状态，收益低于重复占比）。

### D2：预算刹车按终态细分豁免 + 结构化诊断继承

**选择 A（预算）**：`_exempt_dead_run_budget`（`budget.py:117`）的调用判据细化——豁免**仅适用于基础设施性死亡**：run 终态为 `interrupted`（daemon 关闭/重启连带杀）或归因指向网关链路耗尽；**监督超时/被判停滞而杀**（终态 `error` 且 reason 含 `Timeout after ... extension budget exhausted` / `stagnant`）**不豁免**——它确实消耗了整份预算。

**理由**：既有豁免的立论（`fix-budget-counting-semantics`：故障密集日网关死亡烧预算）针对的是**没跑满预算就死**的 run；本案是**跑满并超支**的 run，两者成本语义相反。用同一豁免把后者的计数退掉，等于拆掉了唯一的刹车。

**选择 B（诊断继承）**：新增 spec 级结构化诊断字段（如 `_impl_diagnosis`），由 run 终结时写入（终态类型 + 归因 + 已得出的定性结论 + 已提交进度：分支与已勾选任务）；`_prev_error_section`（`prompt_builder.py:487`）扩展为在 error 文本之外注入该结构化段。链路修正：`_rollback_failed_dispatch`（`dispatch.py:1261-1311`）清 `error` 时 MUST NOT 一并清掉诊断字段。

**理由**：本案前 5 个 attempt 全部重复探测「套件是否真挂起」，只有最后一个换了策略（faulthandler / strace / 基线 worktree 对照）。若第二轮就继承「已定性：存量挂起，无需重探」，可省下大部分时间。

### D3：有界全量套件入口 + 存量归类 + worktree 自举物 skip

**选择**：新增 `bin/run_full_suite.py` 作为**有界全量套件入口**：以硬超时运行 `pytest tests/ -q`，启用 `faulthandler`（`-p faulthandler --faulthandler-timeout=<N>`）以在挂起时打印栈；超时/挂起时中止并输出挂起测试标识。附带 `--baseline <ref>` 模式：在变更前基线（首个提交的父提交）的临时 worktree 中跑同一套件，输出两侧失败集合差异，直接给出「存量 / 本次引入」归类。
- 该入口的路径**仅存在于主树**（`bin/` 入库），worktree 经 `.fenix/bin` 符号链接可达（沿用既有自举布局）。
- `agents/implementer.md` 与 `core/agent_runner/prompt_builder.py` 的 implementer/repair 契约段补：全量回归 MUST 走该有界入口（或等价带超时方式），MUST NOT 裸调 `pytest tests/ -q` 无限等待。
- **worktree 自举物 skip**：`tests/test_block_main_tree_write_hook.py`、`tests/test_planner_scenarios_batching_hook.py` 对 `.fenix/hooks/*` 缺失改为 skip（`pytest.mark.skipif` 或 `pytest.importorskip` 等价），skip 原因指明「自举物未部署（worktree 预期形态）」；主树存在时断言行为不变。

**为什么落在 `bin/` 而非新增框架内服务**：agent 通过 Bash 跑套件，框架无法拦截其任意命令；提供一个**确定性、可复现**的入口并写进契约，是最小可行且可测的收口方式。

### D4：端口分配去 TOCTOU + 套件并发隔离手段

**选择**：`core/proc_utils.py:32 find_free_port()` 改为**不做「探测即释放」**——改为返回「已绑定 socket 的端口」并允许调用方接管该 socket（或提供 `contextmanager` 版本），保留既有返回 int 的 API 作为兼容包装（内部改为绑定失败即重试 N 次）。同时新增**按 run/worktree 派生端口段**的环境变量约定（如 `FENIX_SUITE_PORT_BASE`），供并发套件取互不重叠的段；`FENIX_VERIFY_PORT` 语义不变。
- 并发隔离手段：复用 `bin/run_full_suite.py` 入口加主机级互斥（沿用 `state_machine` 的 fcntl 文件锁范式，锁文件置于 `.fenix/`），同一主机全量套件串行；锁获取结果写日志供复盘。
- 端口探测/隔离策略 MUST 在日志中可观测。

## Risks / Trade-offs

- **[重复占比误判真实推进]** 存在「大量同参数重试但确实在推进」的合法形态（如批量重跑同一命令）。缓解：`HANG_MIN_TOOL_CALLS` 样本下限 + 仅在 deadline 到点时才判定（非全程监控）+ 阈值取 0.75 偏保守；误杀后果有 `_exempt`/重试兜底，且比 10.5h 空转可接受。
- **[预算豁免细分误伤真实网关死亡]** 判据按终态事件类型（`interrupted` vs `error`+timeout reason）区分，粒度足够；网关链路耗尽的归因文案需一并纳入豁免白名单，实施时以本案 `fix-budget-counting-semantics` 的既有归因字符串为准。
- **[有界入口不被 agent 采用]** 单靠新增脚本无强制力。缓解：契约段显式引导 + implementer 提示词；后续可加机械告警（检测裸 `pytest tests/` 长跑）。
- **[worktree skip 掩盖真实回归]** 若某 change 恰好要改 hooks 测试本身，skip 会遮蔽。缓解：skip 原因显式；主树执行路径不变，CI/主树验证仍覆盖。
- **[并发串行降低吞吐]** 主机级互斥会让并发套件排队。权衡：排队成本远低于伪失败导致的误诊与重跑；且端口段隔离优先于互斥，能用隔离就不串行。
