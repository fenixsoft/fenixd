# scenario-schema-single-source 增量规格

## ADDED Requirements

### Requirement: 断言必填字段规则单源定义

各类场景断言与操作的必填字段规则（如 output_match/file_content 需 expected、json_output 需 step 与 path、status_code 需 expected、run 需 command、http_request 需 method/url 等）MUST 收敛为单一权威来源（常量/函数），写端校验与生成侧（planner 指令）MUST 从同一来源派生，MUST NOT 在两处各自维护可漂移的枚举。

#### Scenario: 生成侧与校验侧同源
- **WHEN** 某种断言类型新增/修改必填字段规则
- **THEN** 校验侧与生成侧 MUST 同时生效，MUST NOT 出现生成侧产出与校验规则不一致

### Requirement: 生成侧指令内联必填字段与样例

planner 的场景生成指令 MUST 为每种断言类型给出必填字段说明与合法 JSON 样例（output_match 含 expected 字段、json_output 含 step 与 path 字段等），MUST NOT 仅列类型名；各类操作的必填字段（run 的 command、http_request 的 method/url 等）同样 MUST 给出说明。上述必填字段说明与样例 MUST 由单一权威来源运行时渲染注入（见「断言必填字段规则单源定义」），且 MUST 注入**全部会重写 test_scenarios.json 断言/操作结构的 agent 分支**——planner-plan、fast-track 与 planner-judge 三条分支共用同一渲染（fast-track 在 PHASE 2 自行生成并写入场景集；planner-judge 的原地修复协议要求其直接改写 `{scenarios_path}` 的步骤与断言，见 agents/planner-judge.md 原地修复协议）。administrator 修复通道不在注入范围（其约束段已机械要求写回通过 `validate_scenario_dicts` 门并按框架回传的逐条错误清单重修，走「门 + 错误清单」自纠闭环而非先验盲写）。模板文件 agents/planner-plan.md、agents/fast-track.md MUST NOT 维护与单源可漂移的第二份枚举。

#### Scenario: cli 断言生成合法
- **WHEN** planner 生成 cli 场景断言（output_match / json_output 等）
- **THEN** 产出 MUST 包含各类型必填字段（output_match.expected、json_output.step/path），通过写端校验

#### Scenario: fast-track 生成侧同源
- **WHEN** fast-track run 在 PHASE 2 写入 test_scenarios.json
- **THEN** 其生成指令 MUST 含与 planner-plan 同源的必填字段说明与样例（运行时渲染注入），产出 MUST 通过写端校验，MUST NOT 依赖 agents/fast-track.md 内联的第二份枚举

#### Scenario: judge 原地修复侧同源
- **WHEN** planner-judge 按原地修复协议改写 `{scenarios_path}` 的步骤或断言
- **THEN** 其指令 MUST 含与 planner-plan 同源的必填字段说明与样例（运行时渲染注入），修复后的断言 MUST 通过写端结构校验（`validate_scenario_dicts`），MUST NOT 因缺必填字段被写端门整体剔除

### Requirement: 写盘前客户端预校验逐条剔除

planner 产出在进入阶段2 场景执行前 MUST 先经与写端一致的校验器预检：非法条目按条剔除并留痕（场景 id + 缺失字段），合法条目照常进入执行，MUST NOT 等整批落盘后整批剔除。剔除 MUST 生效于阶段2 实际加载的场景集——加载侧 MUST NOT 因个别非法条目整轮失败并退回重排；同时 MUST 生效于持久化场景集（scenarios.json），两文件 MUST 同源过滤、MUST NOT 分裂。既有语义保留：剔除数超本轮 20% 时 ERROR 升级（可见性兜底，非退回触发器），且该比例 MUST 以写回前最终合法集为基准统计（含补齐写回 pass 的剔除）。剔除后无合法场景可执行时 MUST 由框架**显式**判定验收失败并退回 plan 重排——MUST NOT 依赖场景文件加载报错（写回合法子集后该报错不再触发），MUST NOT 以防空场景集继续进入阶段2 执行与裁决（0 场景报告无失败信号，会被洗白门 fail-open 放行而判 verified，即 0 覆盖「验证通过」），MUST NOT 借助异常通道传递该判定（调用点 except 仅记 WARNING 后继续，信号会被吞并静默退化回老路径），MUST NOT 写入空场景集或空持久化集

#### Scenario: 单条非法不拖垮整批
- **WHEN** planner 产出的个别条目缺少必填字段
- **THEN** 仅该条被剔除并留痕，其余合法条目照常进入执行，MUST NOT 整批作废重跑 planner

#### Scenario: 整批非法仍走退回
- **WHEN** planner 产出条目全部非法、剔除后无合法场景可执行
- **THEN** 框架 MUST 显式判定验收失败并退回 plan 重排，并因剔除数超本轮 20% 触发 ERROR 升级留痕；MUST NOT 写入空场景集或空持久化集、MUST NOT 以 0 场景继续执行（0 场景报告会绕过退回并可能被判 verified）；**AND** 该判定 MUST 经结构化返回值传递到全部调用点（阶段1 主路径与 judge 重入路径），既有持久化集 MUST 保持不变；**AND** 阶段1 主路径重排预算耗尽（`replan_left <= 0`）时 MUST NOT 落入既有「预算耗尽即继续验证」分支——0 场景进入阶段2 执行与裁决即洗白路径，此时 MUST 显式结束本轮（保持待人工/升级留痕），MUST NOT 因无重排预算而放行 0 场景执行