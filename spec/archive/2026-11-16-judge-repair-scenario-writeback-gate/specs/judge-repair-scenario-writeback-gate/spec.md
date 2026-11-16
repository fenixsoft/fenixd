# judge-repair-scenario-writeback-gate 能力规范

## ADDED Requirements

### Requirement: judge 修复写回受理整批校验门
框架受理 judge `scenario-repaired` 申报时，MUST 在采纳前对盘上场景集原始 JSON 数组执行与结构化写端 `_exec_revise_scenario_reverify` 同源的整批校验（`validate_scenario_dicts`，含 per-kind 词表）。任一条非法时本轮修复 MUST 被整体拒收（fail-closed）：不进入场景剔除继续流程、不重入执行，MUST 按既有拒收语义留痕（error 含逐条错误清单、spec 保持 testing、修复申报记账 rejected）并返回已消费（MUST NOT 穿透调用方守卫）。全部合法时 MUST 照常进入既有冻结收编与重入流程，行为零变化。

#### Scenario: 词表违规条目拒收本轮修复
- **WHEN** judge 修复写回的场景集中任一条目含跨 kind 词表违规（如 api 场景 steps 携带 `run` 步骤）并申报 `scenario-repaired`
- **THEN** 受理时整批拒收本轮修复：error 留痕含该条目的词表错误描述、spec 保持 testing、本轮不重入执行场景、修复申报记账为 rejected

#### Scenario: 全部合法正常受理
- **WHEN** judge 修复写回的场景集全部通过整批校验并申报 `scenario-repaired`
- **THEN** 照常进入既有冻结收编与重入执行流程，行为与本门引入前一致

#### Scenario: 拒收不穿透守卫
- **WHEN** 预检拒收分支被消费
- **THEN** 调用方收到「scenario-repaired 已由专门分支消费」信号并终止当前调用，MUST NOT 落入平铺尾段把未重执行的 spec 假收敛为 verified

### Requirement: 受理采纳成对落盘
预检通过后的受理采纳写回 MUST 满足成对纪律：`test_scenarios.json` 与 `_scenarios_full.json` 以同一版本戳成对覆盖，落盘顺序为先 `_scenarios_full.json` 后 `test_scenarios.json`（对账回填以 `test_scenarios.json` 为权威源，中断撕裂对须收敛回旧一致态）。MUST NOT 出现「主文件已更新而备份停留旧集」的撕裂窗口。

#### Scenario: 采纳后两文件成对一致
- **WHEN** 预检通过的修复被受理采纳并写回
- **THEN** `test_scenarios.json` 与 `_scenarios_full.json` 内容一致且携带同一契约版本戳

#### Scenario: 中断撕裂对收敛回旧一致态
- **WHEN** 成对写入在第二文件写入前被中断
- **THEN** 下轮对账以 `test_scenarios.json` 为权威源收敛，MUST NOT 用旧备份定义回填覆盖新修复

### Requirement: 拒收语义与预算口径兼容
写端校验拒收 MUST 复用既有拒收先例的记账与预算口径：消耗既有修复预算（`_SCENARIO_REPAIR_MAX_ROUNDS` 不变），逐条错误清单经既有重派上下文回传下轮 judge 重修；修复预算耗尽持久态下的「无修复纯归因模式」语义 MUST 不因本门改变。

#### Scenario: 错误清单回传重修
- **WHEN** 本轮修复因校验失败被拒收
- **THEN** 下轮 judge 重派上下文携带逐条错误清单，judge 可按清单定向重修；预算按既有口径递减，不新增轮次

#### Scenario: 耗尽态拒收语义不变
- **WHEN** 修复预算耗尽持久态已置位且 judge 再次申报修复
- **THEN** 既有「无修复纯归因模式」拒收优先于本门预检，拒收文案与记账行为与本门引入前一致
