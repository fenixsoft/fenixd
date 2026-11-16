# planner-scenario-schema Specification

## ADDED Requirements

### Requirement: 规划提示词明示 timeout 单位

planner-plan 的提示词与场景模板 MUST 显式声明 timeout 及 sse_connect duration 等以秒计的时长字段单位为秒，并给出合法示例值（不超过校验上限 1800 秒）；MUST NOT 留空单位语义让规划器自行猜测。

#### Scenario: 新规划产出秒级 timeout

- **WHEN** planner-plan 按更新后提示词产出场景集
- **THEN** 场景时长字段（timeout/duration）值为秒级数值且全部通过写前预校验的量级检查

### Requirement: 非法 timeout 报错带换算嫌疑提示

写前预校验对「值超上限且可被 1000 整除」的 timeout/duration MUST 在报错中附加「疑似毫秒（建议除以 1000）」提示；报错 MUST 继续回显数值与上限。下方两 Scenario 对 duration 字段同款适用。

#### Scenario: 毫秒形态值触发嫌疑提示

- **WHEN** 校验遇到 timeout=1800000.0（上限 1800 秒）
- **THEN** 报错包含「疑似毫秒」换算提示，退回重排的规划器可在下一轮直接按秒改写

#### Scenario: 秒级超限不误报嫌疑

- **WHEN** timeout=2400（秒级但超上限、不可被 1000 整除）
- **THEN** 报错只回显超限事实，不附毫秒嫌疑提示

### Requirement: 单位错误不落盘

含非法 timeout 的场景集 MUST NOT 持久化为冻结场景文件，按既有写前预校验语义整批退回重排（现状保持，本 SPEC 不改变该闸门行为）。

#### Scenario: 整批拒绝不产生空文件

- **WHEN** 场景集存在任一非法 timeout
- **THEN** 场景文件不被写入，既有退回重排流程照常执行