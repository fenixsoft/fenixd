## Why

2026-09-13 两批次 planner 产出场景 100% 被写端校验剔除：06:55:24Z 剔除 25/25 条（scale-estimate-*，output_match 缺 expected，对应 evo-add-fast-track-scale-precheck），07:08:13Z 剔除 17/17 条（blind-run-marker-*，json_output 缺 step，对应 evo-add-self-review-run-semantics）；更早在 09-12 已有 json_output 缺 path 同源事件。剔除均触发 plan 阶段退回+重排+重新生成 planner（各消耗一轮 planner run），回退后靠 synthesis fallback 场景通过验收。根因：写端校验规则（core/verify_engine/scenarios.py:585-600：output_match/file_content 需 expected、json_output 需 step+path）与 planner 生成指令（agents/planner-plan.md:94-96 仅列断言类型名、未说明各断言必填字段）不一致——生成侧 schema 漂移，LLM 只能猜断言结构。evo-add-frozen-scenario-schema-migration（17650012）只修了读侧（旧文件加载迁移），写侧生成未跟随。

## What Changes

- 断言 schema 单源化：把各类断言的必填字段规则（output_match 需 expected、json_output 需 step+path 等）收敛为单一权威定义（core/verify_engine/scenarios.py 常量/函数派生），planner 生成侧与写端校验共用同一来源。
- planner system prompt 注入当前合法断言模板：agents/planner-plan.md 为每种 cli/api 断言类型给出必填字段说明与合法 JSON 样例（output_match 含 expected、json_output 含 step+path）；该注入为**三条会重写 test_scenarios.json 断言/操作结构的 agent 分支共用**——planner-plan、fast-track（agents/fast-track.md 的 PHASE 2 同样直接写 test_scenarios.json）与 planner-judge（原地修复协议要求其直接改写 `{scenarios_path}` 的步骤与断言，agents/planner-judge.md 原地修复协议）；agents/fast-track.md 内联的第二份 schema/枚举同步收敛到单源。administrator 修复通道不进注入范围（已由「写回必过 validate_scenario_dicts 门 + 按回传错误清单重修」自纠闭环覆盖）。
- 写盘前客户端预校验：planner 产出后、进入阶段2 执行前调用同一校验器，非法条目按条剔除留痕，且剔除须生效于阶段2 实际加载的场景集（而非仅记账——既有实现只记账不改文件，非法条目仍令加载失败并整轮退回重排）。
- 无 dashboard UI、无新配置键。

## Capabilities

### New Capabilities
- `scenario-schema-single-source`: 断言 schema 生成侧与校验侧共用单源定义，planner 产出写前逐条预校验

### Modified Capabilities
无 requirement 级修改：写端校验规则本身不变（仍按 scenarios.py 拒绝非法断言），本能力消除生成侧与校验侧的来源分裂，并把整批剔除改为写前逐条预检。

## Impact

- **core/verify_engine/scenarios.py**：断言必填字段规则收敛为可被生成侧引用的权威常量/函数。
- **core/agent_runner/prompt_builder.py**：planner-plan / fast-track / planner-judge 三分支新增断言 schema 注入段，运行时从单源渲染必填字段与样例（administrator 分支不加，保持「门 + 错误清单」自纠边界）。
- **agents/planner-plan.md**：仅保留指向注入段的最小说明（不手写第二份可漂移枚举）。
- **agents/fast-track.md**：PHASE 2 内联的 schema 样例与 web 断言/操作枚举同样收敛到注入段（fast-track 是第二条场景生成侧）。
- **core/pm_engine/verification.py**：planner 产出经同一校验器逐条预检，非法条目剔除留痕，且剔除生效于阶段2 加载的场景集与持久化集（scenarios.json）两处；空集判定经结构化返回值传给全部调用点（阶段1 与 judge 重入），不写空文件、不进阶段2。
- **tests/**：生成样例与校验规则一致性断言 + 预校验触发断言。