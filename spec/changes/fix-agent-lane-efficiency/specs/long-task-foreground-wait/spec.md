# long-task-foreground-wait — 长任务前台有界等待（新增）

## ADDED Requirements

### Requirement: 长任务的前台有界等待契约

可能超过工具单次调用时限（600s）的长任务（全量回归、大范围构建、超时探针等），prompt SHALL 注入以下契约：

1. **一次后台启动**：MUST 用**一次**后台调用（`run_in_background: true`）启动该任务，MUST NOT 用 `sleep` / 周期性 `ps` 轮询模拟等待；
2. **等待或并行独立工作**：启动后 MUST 等待完成通知，或在等待期间做与该任务无数据依赖的独立工作；MUST NOT 启动后直接收工（「启动即忘」）；
3. **有界入口优先**：若任务存在能在 600s 内返回的有界入口（如 `bin/run_full_suite.py --timeout <t>`），MUST 优先直接前台跑该入口。

提示词 MUST NOT 声明与本条矛盾的能力描述（如「本车道无后台节拍」），除非有实测证据支持。

#### Scenario: 实现者车道契约段含后台等待规则
- **WHEN** 构建 `implementer` / `fast-track` 车道 prompt
- **THEN** 含「一次后台启动 + 等待通知或并行独立工作」的契约文本

#### Scenario: 不再声明「无后台节拍」
- **WHEN** 构建实现者车道 prompt
- **THEN** 结果文件硬门段不含「本车道无后台节拍」这一表述（该表述与实际后台完成通知能力不符）

#### Scenario: 有界入口优先
- **WHEN** 存在 600s 内可返回的有界入口
- **THEN** 契约要求优先使用该入口而非后台等待
