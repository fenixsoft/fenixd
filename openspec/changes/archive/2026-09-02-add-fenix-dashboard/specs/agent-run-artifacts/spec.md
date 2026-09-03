## ADDED Requirements

### Requirement: Agent 运行过程流式落盘
`core/agent_runner.py` 的 `_run_claude` 在启动 implementer / verifier / planner（含 planner-plan、planner-judge）子进程时，MUST 以流式方式运行 `claude -p`（`subprocess.Popen`），并携带 `--output-format stream-json`。运行期间产生的每一行 JSON 事件（`system` / `assistant` / `user` / `tool_use` / `tool_result` / `result` 等）MUST 原样追加写入该次运行的产物文件 `.fenix/runs/<run_id>.jsonl`，其中 `<run_id>` 与现有 run_id 一致（如 `impl-<spec>-<ts>`）。写文件必须在 Agent 启动后立即可见（追加写、逐行 flush），使 Dashboard 可在运行期间轮询读取。非 JSON 行（如 stderr 噪声）MUST 以 `{"type":"stderr","line":...}` 形式兜底写入，保证产物文件始终可逐行解析。

#### Scenario: 运行期间产物文件实时增长
- **WHEN** 一个 implementer Agent 正在运行且已产生至少一条 LLM 事件
- **THEN** `.fenix/runs/impl-<spec>-<ts>.jsonl` 已存在且包含该事件的 JSON 行，且后续事件持续追加

#### Scenario: stderr 噪声兜底可解析
- **WHEN** claude 子进程向 stderr 输出了非 JSON 文本行
- **THEN** 该行以 `{"type":"stderr","line":"..."}` 形式写入产物文件，且文件其余行仍可逐行 JSON 解析

### Requirement: 最终结果与现有解析兼容
改造后，`_run_claude` 的返回 MUST 与现状等价：从流的最终 `result` 事件中取回结果 JSON（含 `num_turns` 等字段），作为返回的 `output` 与 `turns`；若 Agent 正常结束，产物文件末尾 MUST 包含该 `result` 事件行。若进程异常退出、超时或被 kill，产物文件 MUST 追加一行 `{"type":"error","error":<描述>,"exit_code":<码>}` 终态行，`_run_claude` MUST 仍按现状语义抛出 `RuntimeError`。现有调用方（`AgentRunResult`、verifier 读取 `.fenix-run-result.json`、重试与日志）的行为 MUST 不因本次改造改变。

#### Scenario: 正常完成返回与现状一致
- **WHEN** implementer Agent 成功完成并输出最终 result 事件
- **THEN** `_run_claude` 返回的 `output` 与 `turns` 与使用 `--output-format json` 时的解析结果等价，且产物文件包含 result 事件行

#### Scenario: 超时或异常时写终态行并抛错
- **WHEN** Agent 进程超时被 kill 或以非零码退出
- **THEN** 产物文件追加 `{"type":"error",...}` 终态行，`_run_claude` 抛出 `RuntimeError`，且半成品 jsonl 文件仍可被 Dashboard 读取展示

### Requirement: 运行产物保留与清理
`.fenix/runs/` 目录 MUST 仅保留最近 N（默认 20）个运行的产物文件；Dashboard 启动时或每次聚合读取时 MUST 清理超出数量的最旧文件（删除时跳过正在增长的活动产物）。`.fenix/runs/` MUST 加入框架模板 gitignore，避免运行产物进入版本控制。

#### Scenario: 超出保留上限被清理
- **WHEN** `.fenix/runs/` 中产物文件数量超过保留上限且存在非活动的旧文件
- **THEN** 最旧的、非活动的产物文件被删除，活跃产物文件不受影响

#### Scenario: 运行产物不入版本控制
- **WHEN** 执行 `git status`
- **THEN** `.fenix/runs/` 下的产物文件不显示为待提交变更
