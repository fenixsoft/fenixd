# agent-prompt-files — 长车道契约段扩展（增量）

## ADDED Requirements

### Requirement: 动态契约段的注入顺序不变式

`_build_prompt` 在追加新增动态契约段（「工具调用效率」「取证深度上限与输出裁剪」「长任务前台有界等待」）时，MUST 保持既有段落顺序不变式：`_task_progress_contract_section` → `_result_gate_section` → 其余段 → `_noninteractive_contract_section` → 项目级附加段。新增段 MUST NOT 插到项目级附加段（`_project_extra_section`）之后，MUST NOT 破坏既有顺序断言测试。开关关闭或条件不满足时 MUST 返回空串（零注入，prompt 逐字节不变）。

#### Scenario: 顺序断言仍通过
- **WHEN** 构建含全部动态段的实现者 prompt
- **THEN** 段落相对顺序与既有顺序断言一致，新增段位于项目级附加段之前

#### Scenario: 条件不满足零注入
- **WHEN** 某新增段的启用条件不满足（如开关关闭）
- **THEN** 该段返回空串，prompt 与不含该段时逐字节一致

### Requirement: 既有无后台节拍表述的修正

`_result_gate_section` 的实现者分支（`implementer` / `fast-track`）MUST NOT 再声明「本车道无后台节拍」——该表述与实际的后台任务完成通知能力不符（转录中有成对的 `task_notification` 完成事件为证），是 `sleep` 轮询反模式的成因。修正后的表述 MUST 与 `long-task-foreground-wait` 能力的契约一致。

#### Scenario: 硬门段不再含矛盾表述
- **WHEN** 构建 `implementer` / `fast-track` prompt
- **THEN** 结果文件硬门段不含「无后台节拍」字样，且含与前台有界等待契约一致的表述
