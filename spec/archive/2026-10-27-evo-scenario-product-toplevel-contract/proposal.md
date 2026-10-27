## Why

pack2-official-encoder 重验证筹备中，round-3 场景规划 run（planner-plan-pack2-official-encoder-1791272592-a1，65 轮/$4.71）产物 test_scenarios.json 顶层写成 {"spec":…,"scenarios":[…]} dict，被读端硬门（core/verify_engine/scenarios.py:1545-1547，非数组顶层直接抛「场景文件格式错误: 期望JSON数组」）整份拒收；重试轮未做「解包一行」的最小修复而是全量重建 25 个场景（继任 run 51 轮/$3.90，两轮合计 $8.61/116 轮）。核查证实：被拒产物并未被框架销毁（拒收→replan 路径不删文件，round-4 开场仍在盘上且被完整枚举），真正放大器是 REPLAN_FEEDBACK 文案硬编码「重新输出全部场景」（core/pm_engine/verification/pipeline.py:2748-2754）加 agent 自选全量重建；而规划任务书（agents/planner-plan.md）只有顺带式「合法 JSON 数组」，无显式顶层契约与正反例，且同目录 scenarios.json 本身就是 dict 形态（core/verify_scenarios.py:279-284），两文件同目录形状相反、模板未作区分，是天然混淆源。

## What Changes

1. 顶层契约钉进规划任务书：agents/planner-plan.md 显式声明 test_scenarios.json 顶层必须是纯 JSON 数组（附正反例各一行、显式区分 scenarios.json 的 dict 形态）；core/agent_runner/prompt_builder.py 场景 schema 段单源注入同一契约，静态模板与运行时提示词双保险。
2. 拒收路径最小修复：验收失败路径识别「dict 且含 scenarios 数组」的可拯救形态，机械解包重过全部校验后采纳并留痕；其余格式类失败在 REPLAN_FEEDBACK 按失败类别生成「最小修复」指引，仅内容类缺失才保留「重新输出全部场景」。

## Out of Scope

- 不改冻结层 scenario_gate 的顶层非列表「告警跳过」语义（core/pm_engine/verification/scenario_gate.py:167-173）。
- 不动 judge 结果文件生命周期（evo-add-judge-result-predispatch-rename 已覆盖，其非目标显式排除 scenarios 产物）。
- 不做条目级 schema 变更（归档 evo-planner-scenario-schema-alignment 已覆盖条目级注入，本 SPEC 只补顶层级）。
- 不建产物快照/回收站机制（核查证实产物并未被销毁，无需保留现场设施）。