# judge 修复场景写回受理门

<!-- knowledge: capability=judge-repair-scenario-writeback-gate rev=1
     sources=spec/changes/judge-repair-scenario-writeback-gate -->

judge 原地修复协议改写场景文件后的框架受理门：在 `scenario-repaired` 申报采纳瞬间拦截结构性非法修复、保证场景集双文件成对一致，不让机械可判违规潜伏到验收期执行才暴露。

## 规则

- **受理整批校验（fail-closed）**：框架受理 judge `scenario-repaired` 申报时，采纳前对盘上场景集原始 JSON 数组执行 `validate_scenario_dicts` 整批校验（与 admin 修订通道唯一结构化写端同源，含 per-kind 操作词表——api 场景 steps 携带 `run` 步骤即违规）。任一条非法即整体拒收本轮修复：不进入场景剔除继续流程、不重入执行场景。
- **拒收接线既有先例**：`update_spec` error 留痕（文案含写端校验失败拒收与逐条错误清单前 3 条）、spec 保持 testing、修复申报记账 rejected、返回已消费信号终止当前调用（MUST NOT 返回 False 穿透调用方守卫，否则未重执行的 spec 落入平铺尾段被假收敛为 verified）。
- **错误清单驱动重修**：逐条错误清单经既有重派上下文（prev-error 注入链）回传下轮 judge 定向重修；拒收轮消耗既有场景修复预算（`_SCENARIO_REPAIR_MAX_ROUNDS`），不新增预算轮次；修复预算耗尽持久态的「无修复纯归因模式」拒收优先于本门预检，文案与记账不变（见 [judge 修复预算口径统一](judge-repair-budget-alignment.md)）。
- **受理采纳成对落盘**：预检通过后的写回以同一契约版本戳成对覆盖 `test_scenarios.json` 与 `_scenarios_full.json`，落盘顺序固定先 `_scenarios_full.json` 后 `test_scenarios.json`（对账回填以 `test_scenarios.json` 为权威源，中断撕裂对收敛回旧一致态）。MUST NOT 出现「主文件已更新而备份停留旧集」的撕裂窗口——否则「无理由缺场景按持久化集回补」分支会把旧定义复辟。
- **语义分化边界**：planner 产出收编路径（剔除继续：坏条目剔除留痕、合法子集照常执行）、admin `revise_scenario_reverify` 通道、fast-track Phase 2 写入车道（自带独立 schema 门）均不经本门，行为零变化；`_apply_scenario_freeze` 空集拒绝分支保留为预检通过后的防御性兜底。修订通道 fail-closed 与产出收编剔除继续的分化裁定见 [ADR-318](../../adr/ADR-318-scenario-repair-acceptance-failclosed-split-from-intake.md)。
- **协议模板是第一道防线**：planner-judge 原地修复协议段声明写回将按整批校验受理、任一条非法（含词表违规）即拒收并按逐条错误清单重修，以及申报前自校验义务；强制力在受理点机械门，prompt 层约束会被模型漂移突破，不作为唯一防线。
- **拦截能力边界**：本门只拦机械可判违规（结构必填、per-kind 词表、JSON 形态、成对撕裂窗口）；端口/URL 客观错误、断言弱化、选择器失配等语义级错误不在校验能力内，仍靠验收期执行与 judge 出题同源知识兜底。

## 关键行为

受理分支顺序固定：预算检查 → 耗尽两态拒收（既有）→ 结构预检拒收（本门）→ 冻结收编（成对落盘）→ 空集拒绝兜底 → 重入执行。预检读盘原始 JSON 数组，非空错误清单即拒收本轮修复（error 留痕 + rejected 记账 + 返回已消费）；全部合法则照常进入冻结收编与重入执行。

## 溯源

- 2026-11-03 judge-repair-scenario-writeback-gate（spec/changes/judge-repair-scenario-writeback-gate/） — 新增本能力：judge 原地修复写回受理点挂 fail-closed 整批结构校验（机械可判违规受理即拒收、错误清单回传重修、拒收不穿透守卫、预算口径不变）+ 受理采纳成对落盘（同版本戳、先备份后主文件、撕裂对收敛回旧一致态）；planner 收编剔除继续、admin 修订通道、fast-track 写入车道零变化。动因：judge 直改场景文件绕过写端门，词表违规潜伏 2 轮至验收期、旧备份经对账回填使端口漂移复辟。
