# 验证报告：evo-planner-scenario-schema-alignment

> ⚠️ 本报告由框架于 2026-09-14T14:29:59Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-14T14:29:59.165530+00:00

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.32M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| schema-consistency-output-match | D1 单源一致性：output_match 缺 expected 字段 → validate_scenario_dicts 校验拒绝并指明缺失字段（核心回归点：2026-09-13 剔除事故的直接复现路径）。来源：core/verify_engine/scenarios.py:246-248。 | pass | 0/3 | - |
| schema-consistency-json-output | D1 单源一致性：json_output 缺 step + path 字段 → 校验拒绝并输出两条错误（产出 2026-09-13 两批 100% 剔除的第二类根因）。来源：core/verify_engine/scenarios.py:255-259。 | pass | 0/3 | - |
| schema-consistency-status-code | D1 + 4.3 等价性回归：status_code 缺 expected 非法；expected=0 合法（include_zero 语义，0 值不判空）。来源：core/verify_engine/scenarios.py:262-264。 | pass | 0/2 | - |
| schema-consistency-api-method-url | D1 单源一致性：http_request 缺 method + url 两个必填字段 → 校验拒绝；run 缺 command → 校验拒绝。验证 ACTION_REQUIRED_FIELDS 对 api 与 cli 步骤的约束。来源：core/verify_engine/scenarios.py:299-315。 | pass | 0/2 | - |
| schema-consistency-valid-complete | D1 正向路径：合法完整的 cli 场景（output_match 含 expected + json_output 含 step+path）与 api 场景（http_request 含 method+url + status_code 含 expected + json_path 含 path）通过 validate_scenario_dicts，输出空错误列表。 | pass | 0/3 | - |
| prompt-injection-planner-plan | D2 prompt 注入（第一条写入车道）：planner-plan 分支 prompt 含「场景断言/操作必填字段」注入段，含 output_match 预期字段 expected 与合法 JSON 样例，含 run command 样例。来源：core/agent_runner/prompt_builder.py:249-251。 | pass | 0/4 | - |
| prompt-injection-fast-track | D2 prompt 注入（第二条写入车道）：fast-track 分支 prompt 含同一注入段，含 status_code 所需 expected 字段与样例。agents/fast-track.md 内联枚举已收敛到此段。来源：core/agent_runner/prompt_builder.py:300-303。 | pass | 0/3 | - |
| prompt-injection-planner-judge | D2 prompt 注入（第三条写入车道）：planner-judge 分支 prompt 含注入段，含 json_output 必填字段 step/path 与合法 JSON 样例。judge 原地修复协议可从此段获取准确字段信息。来源：core/agent_runner/prompt_builder.py:280-283。 | pass | 0/3 | - |
| prompt-injection-administrator-absent | D2 边界保持（2.4）：administrator prompt 不含「场景断言/操作必填字段」注入段——admin 走「validate_scenario_dicts 门 + 按框架回传的逐条错误清单重修」自纠闭环，不注入先验 schema 知识。来源：core/agent_runner/prompt_builder.py:315-319。 | pass | 0/2 | - |
| prevalidation-single-invalid | D3 单条非法不拖垮整批（3.1-3.4）：构造含 1 条非法 web 场景（缺 navigate）+ 1 条合法 web 场景的 planner 产出，调用 _apply_scenario_freeze，断言：非法条目被剔除留痕、合法条目写回 test_scenarios.json 且可通过 load_scenarios 阶段2 加载。来源：core/pm_engine/verification.py:1252-1325。 | pass | 0/2 | - |
| prevalidation-all-invalid-abort | D3 整批非法走退回（3.5/3.8）：构造全非法 planner 产出（2 条均缺 kind/steps），调用 _apply_scenario_freeze，断言返回 {'aborted': 'no_valid_scenarios', ...}，含 rejected 列表与逐条错误描述，原始非法条目仍保留在文件中（未写空）。来源：core/pm_engine/verification.py:1291-1311。 | pass | 0/2 | - |
| prevalidation-persisted-unchanged | D3 空集持久化不变（3.8）：构造全非法 planner 产出 + 预置持久化集 scenarios.json 含既有场景，调用 _apply_scenario_freeze，断言：空集判定先于 save_scenario_set，不写空 test_scenarios.json，持久化集 scenarios.json 保持原有条目不变。来源：core/pm_engine/verification.py:1291-1296。 | pass | 0/2 | - |
| prevalidation-rejected-covers-stored | D3.10 剔除留痕：被预校验剔除的条目 id 与 covers 列表存入 vpipe._last_freeze_rejected / _last_freeze_rejected_covers，供 _apply_interaction_contract 区分「条目非法剔除」缺口与「设计漏项」缺口，避免重排-剔除循环。来源：core/pm_engine/verification.py:1277-1289。 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

