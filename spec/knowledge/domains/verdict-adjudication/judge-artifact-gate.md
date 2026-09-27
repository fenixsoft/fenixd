<!-- knowledge: capability=judge-artifact-gate rev=2 sources=spec/archive/2026-09-14-add-judge-artifact-gate,spec/archive/2026-09-22-fix-impl-resultfile-contract-gap -->

# judge 产物硬门

agent run 成功判定的结果文件存在性硬门：exit 0 不等价于成功，无产物按瞬态失败原地退避重试，且不侵占裁决重试预算；契约段对全部受约束车道可见。

## 现行规则

- `agent_runner` 对 `planner-judge` run 的成功判定为「进程 exit 0 **且**结果文件（`.fenix/verify-progress/<spec>/.fenix-run-result.json`）存在且可解析为非空 JSON」；任一条件不满足判 `success=False` 并附产物缺失归因 error，走既有瞬态原地退避重试通道，不触发 `_verify_verdict_evidence` 的「裁决重试一次」路径。
- 结果文件存在但内容为空或非法 JSON，与缺失同判（`success=False` + 瞬态重试）。
- `planner-plan` run 的成功判定同样要求 `test_scenarios.json` 存在且可解析；场景冻结复用轮不派发 planner-plan，硬门对其无影响。
- 重试预算分离：产物缺失引起的重试不消耗 `_verify_verdict_evidence` 的「裁决重试一次」预算，该预算专用于「产物存在但不合规」（validate_report 违规）路径；硬门重试与裁决重试两次计数独立、互不侵占。
- 产物硬门契约段的提示词可见性覆盖全部受硬门约束的 agent 车道：`planner-plan`、`planner-judge`、`spec-review`、`implementer`、`fast-track`；契约段内容声明「收工前未写 / 文件为空 / 非法 JSON → 判失败并原地重试（fail-closed）」与「先落盘再深入」。
- 结果文件路径按 agent_type 分派计算，各车道提示词给出的路径与其 runner 侧硬门实际校验路径同源（避免双实现漂移）。

## 溯源

- 2026-09-14 add-judge-artifact-gate — 确立 planner-judge / planner-plan 结果文件存在性硬门（exit 0+产物双条件、缺失走瞬态退避重试）与硬门/裁决双预算分离
- 2026-09-22 fix-impl-resultfile-contract-gap — 硬门契约段注入车道扩展至五车道（补齐 implementer / fast-track 缺口），路径计算按 agent_type 分派并与 runner 侧同源
