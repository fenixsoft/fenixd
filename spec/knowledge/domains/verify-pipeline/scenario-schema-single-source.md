# 场景结构单源
<!-- knowledge: capability=scenario-schema-single-source rev=1 sources=spec/archive/2026-09-19-evo-planner-scenario-schema-alignment -->

场景断言/操作的必填字段规则单源化：生成侧与校验侧共用同一权威定义，planner 产出写盘前逐条预校验，整批报废与空集洗白双堵。

## 现行规则

- 必填字段规则单源定义：各类场景断言与操作的必填字段规则（output_match/file_content 需 `expected`、json_output 需 `step` 与 `path`、status_code 需 `expected`、run 需 `command`、http_request 需 `method`/`url` 等）收敛为单一权威来源（常量/函数）；写端校验与生成侧（planner 指令）从同一来源派生，不在两处各自维护可漂移的枚举。
- 生成侧指令内联必填字段与样例：planner 的场景生成指令为每种断言类型给出必填字段说明与合法 JSON 样例（不得仅列类型名）；说明与样例由单一权威来源运行时渲染注入，且注入全部会重写 `test_scenarios.json` 断言/操作结构的 agent 分支——planner-plan、fast-track（PHASE 2 自行写场景集）与 planner-judge（原地修复协议直接改写 `{scenarios_path}`）三条分支共用同一渲染。administrator 修复通道不在注入范围（其约束段机械要求写回通过 `validate_scenario_dicts` 门并按框架回传的逐条错误清单重修，走「门 + 错误清单」自纠闭环）。模板文件 agents/planner-plan.md、agents/fast-track.md 不维护与单源可漂移的第二份枚举。
- 写盘前客户端预校验逐条剔除：planner 产出在进入阶段 2 场景执行前，先经与写端一致的校验器预检——非法条目按条剔除并留痕（场景 id + 缺失字段），合法条目照常进入执行；不得等整批落盘后整批剔除、不得因个别非法条目整轮失败退回重排。剔除生效于阶段 2 实际加载的场景集与持久化集（scenarios.json）两处，同源过滤、不分裂。
- 剔除可见性：剔除数超本轮 20% 时 ERROR 升级留痕（可见性兜底，非退回触发器），比例以写回前最终合法集为基准统计（含补齐写回 pass 的剔除）。
- 空集显式失败：剔除后无合法场景可执行时，框架显式判定验收失败并退回 plan 重排——经结构化返回值传递到全部调用点（阶段 1 主路径与 judge 重入路径）；不写空场景集或空持久化集、不以 0 场景继续进入阶段 2 执行与裁决（0 场景报告无失败信号，会被洗白门 fail-open 放行判 verified）、不依赖场景文件加载报错或异常通道传递该判定。阶段 1 主路径重排预算耗尽（`replan_left <= 0`）时不得落入「预算耗尽即继续验证」分支放行 0 场景执行，须显式结束本轮并保留待人工/升级留痕。

## 溯源

- 2026-09-19 evo-planner-scenario-schema-alignment — 新增断言必填字段规则单源化、三条生成分支共用运行时渲染注入、写盘前逐条预校验与空集显式失败（此前写端校验规则与 planner 生成指令两源漂移，出现 25/25、17/17 条整批被剔除退回的重复浪费）
