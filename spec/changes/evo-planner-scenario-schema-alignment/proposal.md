## Why

2026-09-13 两批次 planner 产出场景 100% 被写端校验剔除：06:55:24Z 剔除 25/25 条（scale-estimate-*，output_match 缺 expected，对应 evo-add-fast-track-scale-precheck），07:08:13Z 剔除 17/17 条（blind-run-marker-*，json_output 缺 step，对应 evo-add-self-review-run-semantics）；更早在 09-12 已有 json_output 缺 path 同源事件。剔除均触发 plan 阶段退回+重排+重新生成 planner（各消耗一轮 planner run），回退后靠 synthesis fallback 场景通过验收。根因：写端校验规则（core/verify_engine/scenarios.py:585-600：output_match/file_content 需 expected、json_output 需 step+path）与 planner 生成指令（agents/planner-plan.md:94-96 仅列断言类型名、未说明各断言必填字段）不一致——生成侧 schema 漂移，LLM 只能猜断言结构。evo-add-frozen-scenario-schema-migration（17650012）只修了读侧（旧文件加载迁移），写侧生成未跟随。

## What Changes

- 断言 schema 单源化：把各类断言的必填字段规则（output_match 需 expected、json_output 需 step+path 等）收敛为单一权威定义（core/verify_engine/scenarios.py 常量/函数派生），planner 生成侧与写端校验共用同一来源。
- planner system prompt 注入当前合法断言模板：agents/planner-plan.md 为每种 cli/api 断言类型给出必填字段说明与合法 JSON 样例（output_match 含 expected、json_output 含 step+path）。
- 写盘前客户端预校验：planner 产出后、落盘前调用同一校验器，非法条目按条剔除留痕（而非等整批落盘后整批剔除再重跑 planner）。
- 无 dashboard UI、无新配置键。

## Capabilities

### New Capabilities
- `scenario-schema-single-source`: 断言 schema 生成侧与校验侧共用单源定义，planner 产出写前逐条预校验

### Modified Capabilities
无 requirement 级修改：写端校验规则本身不变（仍按 scenarios.py 拒绝非法断言），本能力消除生成侧与校验侧的来源分裂，并把整批剔除改为写前逐条预检。

## Impact

- **core/verify_engine/scenarios.py**：断言必填字段规则收敛为可被生成侧引用的权威常量/函数。
- **agents/planner-plan.md**：为各断言类型注入必填字段说明与合法 JSON 样例。
- **core/pm_engine/verification.py**：planner 产出落盘前调用与写端一致的校验器逐条剔除留痕。
- **tests/**：生成样例与校验规则一致性断言 + 预校验触发断言。