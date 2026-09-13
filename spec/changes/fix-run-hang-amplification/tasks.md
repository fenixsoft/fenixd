## Deliverables

```yaml
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/proc_utils.py
  kind: modify
- path: bin/run_full_suite.py
  kind: new
- path: agents/implementer.md
  kind: modify
- path: tests/test_block_main_tree_write_hook.py
  kind: modify
- path: tests/test_planner_scenarios_batching_hook.py
  kind: modify
- path: tests/test_liveness_hang_discrimination.py
  kind: new
- path: tests/test_run_budget_continuity.py
  kind: new
- path: tests/test_full_suite_runner.py
  kind: new
- path: tests/test_port_allocation.py
  kind: new
```

## 1. 挂起判别（hang-discrimination）

- [ ] 1.1 `core/agent_runner/liveness.py` `_liveness_snapshot`：为窗口内工具调用计算指纹（`工具名 + json.dumps(入参, sort_keys=True)`），产出 `repeat_ratio`（最大同指纹簇调用数 / 窗口内工具调用总数）、`top_fingerprint`（`<tool>(<args 摘要>) ×N`）、`tool_calls_in_window`（样本数）
- [ ] 1.2 同文件常量区新增 `HANG_REPEAT_RATIO_THRESHOLD = 0.75` 与 `HANG_MIN_TOOL_CALLS = 12`，注释标注样本依据（本案 run `impl-fix-root-init-import-shadow-*` 窗口内同参数 `TaskOutput` 轮询占绝对多数；小样本下限防偶发重复误判）
- [ ] 1.3 `_supervision_deadline_action`：在「judge_window 内零事件直接判停滞」之后、「LLM 判定」之前插入确定性短路——`tool_calls_in_window >= HANG_MIN_TOOL_CALLS 且 repeat_ratio >= HANG_REPEAT_RATIO_THRESHOLD` → 直接返回 `kill`，reason 形如 `stagnant: repeated identical tool calls (ratio=0.xx, top=...)`，MUST NOT 调用 judge
- [ ] 1.4 `_judge_liveness` prompt 口径修订：输入补 `repeat_ratio`/`top_fingerprint`；口径显式写明「事件数与 I/O 增长 MUST NOT 单独构成 advancing」与「高重复占比 → stagnant」
- [ ] 1.5 短路判定 MUST 写入被监督 run 的 jsonl 与 daemon 日志，证据含 `top_fingerprint` 构成；与「LLM 判定为停滞」在证据文案上可区分
- [ ] 1.6 快照新增 `background_stall` 证据字段（窗口内后台任务其 `output_file` 大小在监督器相邻采样间零增长），供 LLM 判定输入；不做确定性短路

## 2. 预算与诊断连续性（run-budget-continuity）

- [ ] 2.1 `core/pm_engine/budget.py` `_exempt_dead_run_budget`：调用判据细分——仅基础设施性死亡豁免（run 终态 `interrupted`，或归因指向网关链路耗尽）；**监督超时/被判停滞而杀**（reason 含 `Timeout after ... extension budget exhausted` 或 `stagnant`）MUST NOT 豁免
- [ ] 2.2 `core/pm_engine/dispatch.py:1091` 与 `core/pm_engine/engine.py:2219` 的豁免调用点：按 2.1 判据传入/判定，非豁免时保持计数并记录一行可审计日志（spec、终态、原因、是否豁免）
- [ ] 2.3 新增 spec 级结构化诊断字段（`core/state_machine.py` 序列化白名单登记）：run 终结时写入 `终态类型 + 归因 + 已定性结论 + 已提交进度（分支 + 已勾选任务）`
- [ ] 2.4 `core/agent_runner/prompt_builder.py`：把结构化诊断段注入重派 attempt 的 prompt（在既有 `_prev_error_section` 之外或之内扩展），无诊断时逐字节保持现状
- [ ] 2.5 `_rollback_failed_dispatch`（`core/pm_engine/dispatch.py:1261-1311`）清 `error` 时 MUST NOT 清掉结构化诊断字段

## 3. 有界套件入口与存量归类（baseline-blocked-gate）

- [ ] 3.1 新增 `bin/run_full_suite.py`：以硬超时运行全量套件并启用 faulthandler（`-p faulthandler --faulthandler-timeout`），超时/挂起时中止并输出**挂起测试标识**（栈顶用例）；正常结束返回完整结果与退出码
- [ ] 3.2 同入口 `--baseline <ref>` 模式：在 `<ref>` 的临时 worktree 中跑同一套件，输出两侧失败集合差异并给出「存量 / 本次引入」归类；混合情形 MUST 判为存在本次引入回归
- [ ] 3.3 契约引导：`agents/implementer.md` 与 `core/agent_runner/prompt_builder.py` 的 implementer/repair 段补——全量回归 MUST 走有界入口（或等价带超时方式），MUST NOT 裸调 `pytest tests/ -q` 无限等待
- [ ] 3.4 `tests/test_block_main_tree_write_hook.py`、`tests/test_planner_scenarios_batching_hook.py`：`.fenix/hooks/*` 不存在时改 skip（skip 原因指明「自举物未部署（worktree 预期形态）」），主树存在时断言行为不变

## 4. 并发隔离（concurrent-suite-isolation）

- [ ] 4.1 `core/proc_utils.py` `find_free_port`：消除「探测即释放」的 TOCTOU——提供保留已绑定 socket 的分配路径（contextmanager 或等价），保留既有返回 int 的 API 兼容包装并在绑定失败时重试
- [ ] 4.2 新增按 run/worktree 派生端口段的环境变量约定（如 `FENIX_SUITE_PORT_BASE`），供并发套件取互不重叠的段；`FENIX_VERIFY_PORT` 语义不变
- [ ] 4.3 `bin/run_full_suite.py`：加主机级互斥（沿用 `.fenix/` fcntl 文件锁范式），同一主机全量套件串行；锁获取/等待结果写入日志可观测

## 5. 测试

- [ ] 5.1 `tests/test_liveness_hang_discrimination.py`：构造同参数重复工具调用序列 → 断言确定性短路返回 kill 且未调用 judge；构造多样化调用 → 断言不短路；小样本（< `HANG_MIN_TOOL_CALLS`）不短路
- [ ] 5.2 同文件：断言短路判定的 run jsonl 与日志证据含 `top_fingerprint`，且文案可与 LLM 判定区分
- [ ] 5.3 `tests/test_run_budget_continuity.py`：监督超时杀死 run → 断言预算计数**不**回退；`interrupted` 终态 → 断言回退（既有语义保留）
- [ ] 5.4 同文件：断言重派 attempt 的 prompt 含结构化诊断段；无诊断时 prompt 与现状逐字节一致；`_rollback_failed_dispatch` 后诊断字段仍在
- [ ] 5.5 `tests/test_full_suite_runner.py`：模拟挂起套件 → 断言有界入口在超时内中止并报出挂起测试标识；`--baseline` 归类在「存量-only / 引入-only / 混合」三态正确
- [ ] 5.6 `tests/test_port_allocation.py`：并发多进程取端口均能独占绑定成功；绑定被抢占时重试成功
- [ ] 5.7 两 hooks 依赖测试在 `.fenix/hooks/*` 缺失时结果为 skip（非 fail）

## 6. 全量验证与边界复核

- [ ] 6.1 全量回归经本 change 新增的有界入口执行：结果须为「全绿，或失败/挂起全部经 `--baseline` 归为存量」；不得出现未归类的失败
- [ ] 6.2 边界复核：确认未改动 `evo-add-fast-track-scale-precheck` 的任何 artifact；在本 change 的 design 或提交说明中保留「两者边界：evo 管预算档位、本 change 管挂起识别与重试刹车」的结论
- [ ] 6.3 导入收敛与声明对账：`git diff` 确认交付物与 `## Deliverables` 声明段一致，无声明外改动
