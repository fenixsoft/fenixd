# Agent 运行时
> 最后更新：2026-10-13 23:54 UTC+8

Agent 运行时：agent 进程托管与信号处理、非交互运行契约、提示词文件化、run 产物留存、超时与轮次上限生命周期、提示词层效率治理。本域能力页清单如下。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [agent-runner](agent-runner.md) | agent 进程托管与信号处理 | 2026-10-03 04:59 |
| [agent-runner-modules](agent-runner-modules.md) | agent runner 模块化结构 | 2026-10-03 04:59 |
| [agent-noninteractive-contract](agent-noninteractive-contract.md) | agent 非交互运行契约 | 2026-10-03 04:59 |
| [agent-prompt-files](agent-prompt-files.md) | agent 提示词文件化注入 | 2026-10-03 04:59 |
| [agent-run-params-config](agent-run-params-config.md) | agent 运行参数配置 | 2026-10-03 04:59 |
| [agent-run-artifacts](agent-run-artifacts.md) | run 产物目录与转录留存 | 2026-10-03 04:59 |
| [agent-llm-isolation](agent-llm-isolation.md) | 按 provider 隔离 LLM 凭据与配置目录 | 2026-10-03 04:59 |
| [agent-shutdown-interrupt](agent-shutdown-interrupt.md) | agent 优雅中断与停机协议 | 2026-10-03 04:59 |
| [agent-tool-call-efficiency](agent-tool-call-efficiency.md) | 工具调用效率治理 | 2026-10-03 04:59 |
| [long-task-foreground-wait](long-task-foreground-wait.md) | 长任务前台等待策略 | 2026-10-03 04:59 |
| [subagent-model-availability](subagent-model-availability.md) | 子代理模型可用性 | 2026-10-03 04:59 |
| [tool-result-stream-detection](tool-result-stream-detection.md) | 工具结果流事件识别 | 2026-10-03 04:59 |
| [turn-limit-lifecycle](turn-limit-lifecycle.md) | 轮次上限与生命周期锚定 | 2026-10-08 02:22 |
| [impl-run-budget-sizing](impl-run-budget-sizing.md) | 实现 run 轮数预算规模推算 | 2026-10-08 02:22 |
| [per-agent-timeout-override](per-agent-timeout-override.md) | 按 agent 类型超时覆盖 | 2026-10-03 04:59 |
| [host-change-governance](host-change-governance.md) | 宿主系统级变更备份登记与失败终态回滚义务告警 | 2026-10-13 23:54 |
