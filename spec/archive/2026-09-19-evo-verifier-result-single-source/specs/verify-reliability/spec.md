# 验证结果文件单一来源（verifier-result-single-source）

## 需求

### R1 读取单一来源
- verifier 裁决一律读 verify-progress/<spec>/.fenix-run-result.json。
- 主树 .fenix/.fenix-run-result.json 仅作兼容回退：须先通过 role=verifier + spec 戳匹配 + mtime 新鲜度校验，任一不通过视为失效，回退不得作为裁决依据。
- role 校验不得依赖 run_id 可解析（现状 _verifier_result_is_stale 在 run_id 不匹配 `-\d{10,}-a\d+$` 时不判陈旧，是残留 fail-open）。

### R2 写入语义隔离
- 主树共享文件的唯一写入点是 core/agent_runner/runner.py 的 _execute_agent 拷回，写入时按 agent_type 强制带 role 字段（implementer | verifier | planner | judge | repair）与 spec 戳；role 缺失视为旧格式遗留。
- implementer 结果由 engine.py _write_impl_result_snapshot 写 verify-progress/<spec>/impl-result.json（engine.py:879-914，已落地，当前 40 个 spec 有快照），主树共享不再承载 implementer 语义。
- 读侧对 role≠verifier 的主树共享文件的丢弃仅限裁决读路径，不影响 implementer / planner 主树回退与 fast-track 上轮结论读取的既有采信。

### R3 回归测试
- 新增污染回归测试：主树共享文件含 implementer 残留 status=success（role=implementer 或缺 role，run_id 不可解析）时，legacy 与 planner 两路径均不得将其当裁决；unknown-status 走 stale/foreign 护栏 re-dispatch。
- 补机械锚点断言两处裁决读取确实调用统一入口，防测试预先全绿的零变更洗白。

## 验收标准
- 场景：模拟 add-web-ui 误判链（implementer 残留污染主树共享文件且 run_id 不可解析），0 次 blocked 误判。
- 单元测试：双校验回退、role 字段隔离、污染数据 not treated as verdict、统一入口被两路径调用。
