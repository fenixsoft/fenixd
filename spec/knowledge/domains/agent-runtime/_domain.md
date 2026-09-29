# Agent 运行时

Agent 运行时：agent 进程托管与信号处理、非交互运行契约、提示词文件化、run 产物留存、超时与轮次上限生命周期、提示词层效率治理。本域能力页清单如下。

## 能力页

| 能力页 | 简介 |
| --- | --- |
| [agent-runner](agent-runner.md) | agent 进程托管与信号处理 |
| [agent-runner-modules](agent-runner-modules.md) | agent runner 模块化结构 |
| [agent-noninteractive-contract](agent-noninteractive-contract.md) | agent 非交互运行契约 |
| [agent-prompt-files](agent-prompt-files.md) | agent 提示词文件化注入 |
| [agent-run-params-config](agent-run-params-config.md) | agent 运行参数配置 |
| [agent-run-artifacts](agent-run-artifacts.md) | run 产物目录与转录留存 |
| [agent-llm-isolation](agent-llm-isolation.md) | 按 provider 隔离 LLM 凭据与配置目录 |
| [agent-shutdown-interrupt](agent-shutdown-interrupt.md) | agent 优雅中断与停机协议 |
| [agent-tool-call-efficiency](agent-tool-call-efficiency.md) | 工具调用效率治理 |
| [long-task-foreground-wait](long-task-foreground-wait.md) | 长任务前台等待策略 |
| [subagent-model-availability](subagent-model-availability.md) | 子代理模型可用性 |
| [tool-result-stream-detection](tool-result-stream-detection.md) | 工具结果流事件识别 |
| [turn-limit-lifecycle](turn-limit-lifecycle.md) | 轮次上限与生命周期锚定 |
| [per-agent-timeout-override](per-agent-timeout-override.md) | 按 agent 类型超时覆盖 |
