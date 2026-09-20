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

### Requirement: 既有无后台节拍表述的修正与在飞契约同步

`_result_gate_section` 的实现者分支（`implementer` / `fast-track`）的**能力事实描述**（`ScheduleWakeup` 在非交互派发下不产生唤醒）MUST 保留——该事实**未被证伪**：转录中的成对 `task_notification` 完成事件（`.fenix/runs/archive/impl-fix-spec-review-blocking-dispatch-1789819306-a1.jsonl` 含 26 条 `Background command "…"` summary）证的是 **Bash 后台任务**的完成通知可用，**不是** `ScheduleWakeup` 可用。

需修正的是与之并列的**行为约束**：原表述「MUST NOT 采用『后台运行 + 轮询等待』的收尾编排」被模型读作「后台等待即违规」，退化为 `sleep → echo RUNNING` 前台自旋（全库 40 处 `echo RUNNING`）。修正后的表述 MUST 与 `long-task-foreground-wait` 能力的契约一致，并 MUST 明示：后台 Bash 任务的完成通知**真实可用**（与 `ScheduleWakeup` 不可用是两件事）、MUST NOT 用 `sleep` / 周期性 `ps` 自旋模拟等待。

#### Scenario: 能力事实保留、反模式禁令明确

- **WHEN** 构建 `implementer` / `fast-track` prompt
- **THEN** 结果文件硬门段仍声明 `ScheduleWakeup` 在非交互派发下不产生唤醒，且明示后台 Bash 完成通知可用、MUST NOT 用 `sleep` / 周期性 `ps` 轮询

### Requirement: 在飞契约测试与实现的同步

`tests/test_impl_resultfile_contract.py:99` 现断言实现者车道 prompt 含「无后台节拍」字样；`spec/changes/fix-impl-resultfile-contract-gap/specs/impl-resultfile-contract/spec.md:13` 亦把「本车道无后台节拍」列为硬门必备要素。本变更的措辞修正 MUST 同步处置该在飞 SPEC 的契约表述，处置方式二择一并在实现记录中登记：

1. 该 SPEC 仍在 `spec/changes/`（未归档）→ MUST 先行修订其 spec 与测试断言（本变更 `## Deliverables` 已列 `tests/test_impl_resultfile_contract.py`）；
2. 该 SPEC 已归档入 `spec/archive/` → 按归档产物处理，只改测试锚点，不改归档文本。

无论哪种，MUST NOT 留下「本变更要求不出现该字样」与「既有绿测试要求出现该字样」并存的红线冲突。

#### Scenario: 无并存的红线冲突

- **WHEN** 全量套件运行
- **THEN** 实现者车道 prompt 的断言（`tests/test_impl_resultfile_contract.py`）与本变更的措辞一致，无任何断言要求已被本变更删除的文案
