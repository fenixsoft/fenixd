# Agent 成本控制（轮次上限与遥测过滤）
<!-- knowledge: capability=agent-cost-control rev=1
     sources=spec/archive/2026-09-02-fix-fenix-token-waste -->

限制单次 agent run 的轮次上限并过滤遥测噪音事件，防止单 run 无界消耗与产物被遥测灌满。

## 规则

- **轮次上限强制执行**：配置 `agents.max_turns` 作为 claude CLI 单次运行的轮次上限传入（如 `--max-turns`）；未配置时默认 50。implementer/verifier/planner 单次运行轮次不得超过该上限，达到上限自动终止并按失败路径进入重试逻辑，不得无界运行。
- **thinking_tokens 遥测过滤**：读取 claude CLI stream-json 输出时丢弃 `system`/`thinking_tokens` 遥测事件，不写入 `.fenix/runs/` 产物文件。产物文件不含任何 `thinking_tokens` 事件行；其余事件（assistant/user/result/error）完整保留。

## 溯源

- [2026-09-02 2026-09-02-fix-fenix-token-waste](spec/archive/2026-09-02-fix-fenix-token-waste/) — 新增 max_turns 强制执行与 thinking_tokens 遥测过滤，确立单 run 成本上限与产物干净度口径。
