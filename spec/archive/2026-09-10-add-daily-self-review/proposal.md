## Why

今天的全天复盘（发现 61 次秒挂风暴、2.5h planner 丢弃、4 次归档未提交等浪费与失误）依赖用户人工发起、人工取证、人工汇总——这类回顾应当由框架每日自动完成，把复利式改进的取证成本降为零，并为后续 SPEC 立项提供高质量、可追溯的输入。

## What Changes

- **每日定时自省**：daemon 在配置的每晚时间点（错过后补跑）由 Administrator Agent 执行当日工作回顾——失误、浪费、可改进点，数据源为当日 STATE 终态、runs 统计（含秒挂/超时/丢弃）、admin 告警与日志错误聚合。
- **追加写入 todo.md**：回顾结果以固定结构（日期分节 + 浪费/失误/改进点条目）追加到项目根 `todo.md`，每条含证据与建议，清晰度以「新 agent 可据此提出 SPEC」为标准；写入后自动 commit 收口。
- **设置项**：自省开关（enabled）、执行时间（run_at）、todo.md 上下文阅读开关（read_todo，开启时把既有 todo.md 内容注入自省 prompt 以避免重复并跟踪历史条目）；三项均需 Dashboard 设置页界面。
- **不自动创建 SPEC**：自省产出仅供用户阅读判定，框架 MUST NOT 依据 todo.md 自动创建任何 SPEC。

## Capabilities

### New Capabilities

- `daily-self-review`: 每晚定时自省任务（调度、防重复、补跑）、Administrator 通道执行、todo.md 结构化追加与自动提交、配置开关与 Dashboard 设置页。

### Modified Capabilities

<!-- 无 -->

## Impact

- `core/admin_monitor.py` 或新增自省模块：每日调度判定（时间已过 && 今日未执行 → 触发）、补跑与防重复。
- `core/agent_runner/runner.py` / `prompt_builder.py`：自省 run 类型与 prompt 模板（当日数据摘要 + 可选 todo.md 上下文）。
- `core/config.py`：`admin.self_review` 配置段解析（enabled/run_at/read_todo）与护栏。
- `core/dashboard/data.py` + v3 设置页：三个配置键的读写界面。
- 运行时产物：项目根 `todo.md`（自动 commit）；自省执行状态文件（`.fenix/` 下，记 last_run_date）。
