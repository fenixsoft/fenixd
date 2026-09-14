# scenario-schema-single-source 增量规格

## ADDED Requirements

### Requirement: 断言必填字段规则单源定义

各类场景断言的必填字段规则（如 output_match/file_content 需 expected、json_output 需 step 与 path、status_code 需 expected 等）MUST 收敛为单一权威来源（常量/函数），写端校验与生成侧（planner 指令）MUST 从同一来源派生，MUST NOT 在两处各自维护可漂移的枚举。

#### Scenario: 生成侧与校验侧同源
- **WHEN** 某种断言类型新增/修改必填字段规则
- **THEN** 校验侧与生成侧 MUST 同时生效，MUST NOT 出现生成侧产出与校验规则不一致

### Requirement: planner 指令内联必填字段与样例

planner 的场景生成指令（agents/planner-plan.md）MUST 为每种断言类型给出必填字段说明与合法 JSON 样例（output_match 含 expected 字段、json_output 含 step 与 path 字段等），MUST NOT 仅列类型名。

#### Scenario: cli 断言生成合法
- **WHEN** planner 生成 cli 场景断言（output_match / json_output 等）
- **THEN** 产出 MUST 包含各类型必填字段（output_match.expected、json_output.step/path），通过写端校验

### Requirement: 写盘前客户端预校验逐条剔除

planner 产出落盘前 MUST 先经与写端一致的校验器预检：非法条目按条剔除并留痕（场景 id + 缺失字段），MUST NOT 等整批落盘后整批剔除；合法条目照常落盘。整批剔除（超 20% 阈值）触发退回重排的既有语义保留。

#### Scenario: 单条非法不拖垮整批
- **WHEN** planner 产出的个别条目缺少必填字段
- **THEN** 仅该条被剔除并留痕，其余合法条目照常落盘，MUST NOT 整批作废重跑 planner

#### Scenario: 整批非法仍走退回
- **WHEN** planner 产出超 20% 条目非法
- **THEN** 按既有语义整批剔除并触发 plan 阶段退回重排