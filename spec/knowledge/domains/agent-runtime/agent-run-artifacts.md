<!-- knowledge: capability=agent-run-artifacts rev=2 sources=spec/archive/2026-09-02-add-fenix-dashboard,spec/archive/2026-09-25-fix-agent-lane-efficiency -->

# Run 产物目录与转录留存

agent run 的转录产物契约：流式落盘可运行期回放，终态与指标行追加有序，产物按上限自动清理。

## 现行规则

- 流式落盘：`claude -p --output-format stream-json`（`subprocess.Popen`）运行期间，每行 JSON 事件（`system` / `assistant` / `user` / `tool_use` / `tool_result` / `result` 等）原样追加写入 `.fenix/runs/<run_id>.jsonl`（run_id 与既有命名一致，如 `impl-<spec>-<ts>`）；追加写、逐行 flush，Agent 启动后文件立即可见，Dashboard 可运行期轮询读取。
- stderr 兜底：子进程 stderr 的非 JSON 行以 `{"type":"stderr","line":...}` 形式写入，产物文件始终可逐行 JSON 解析。
- 终态行：正常结束时产物末行含 `result` 事件，`_run_claude` 从该事件取回 `output` 与 `turns`（与既有解析等价）；进程异常退出、超时或被 kill 时追加 `{"type":"error","error":<描述>,"exit_code":<码>}` 终态行并按既有语义抛 `RuntimeError`，半成品文件仍可被读取展示。
- 指标行：终态行（`result` / `error` / `cancelled`）之后追加一行结构化指标事件 `{"type":"run_metrics", ...}`，至少含 `turns`、`context_peak_tokens`、`input_tokens`、`cache_read_input_tokens`、`per_turn_input_tokens`；纯读侧追加，不改既有事件的写入顺序与内容，不参与既有语义判定（Dashboard 读取、末行判定等不受影响）。
- 保留与清理：`.fenix/runs/` 仅保留最近 N（默认 20）个 run 的产物文件；Dashboard 启动时或每次聚合读取时清理超出的最旧文件（跳过正在增长的活动产物）；`.fenix/runs/` 在框架模板 gitignore 中，产物不入版本控制。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：agent run 转录流式落盘为 run 产物，运行过程可回放取证；产物写入与 runs 清理配套
- [2026-09-02 add-fenix-dashboard](spec/archive/2026-09-02-add-fenix-dashboard/) — 固化 stream-json 流式落盘与逐行 flush、stderr 兜底、result/error 终态行与 RuntimeError 语义、runs 保留上限（默认 20）与 gitignore
- [2026-09-25 fix-agent-lane-efficiency](spec/archive/2026-09-25-fix-agent-lane-efficiency/) — 增设终态后 run_metrics 上下文经济性指标行（纯读侧追加，既有事件与读侧不受影响）
