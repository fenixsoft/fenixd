## ADDED Requirements

### Requirement: 批量归因查重拒绝后的重合成回路

框架对批量归因查重（`batch_attribution_dedup`）拒绝的裁决报告，MUST 执行「落盘违规清单 → 派发定向重合成 judge run → 回灌同一校验入口」的闭环，MUST NOT 仅保持 testing 静默等待。

- 违规清单 MUST 经 `verdict_violations.json` 通道落盘（与既有裁决校验违规同源），使重合成 prompt 经 `_verdict_rejection_section` 注入定向修复纪律。
- 重合成 run MUST 只重写被拒场景的归因文本字段（`first_failed_step` / 断言 triage evidence），MUST NOT 重做调查、复现或改写判定与未拒绝场景的任何字段。
- 重合成产物 MUST 回灌完整校验链（`load_report` → `validate_report` → 查重门）后按既有语义推进或拒绝。

#### Scenario: 首次查重拒绝触发重合成而非自锁

- **WHEN** judge 产出报告经查重门检出 ≥3 场景归因逐字相同
- **THEN** 框架落盘违规清单（含被拒场景 id 与重复文本摘要）并派发一个重合成 judge run，spec 保持 testing
- **THEN** 重合成 run 的 prompt 含定向纪律（只改被拒场景归因字段、禁止复现与改判定），且全程不触发全量验证重跑

#### Scenario: 重合成成功回灌推进

- **WHEN** 重合成 run 重写归因后，被拒场景归因文本各异、通过完整校验链
- **THEN** 报告按既有语义采纳（verified/bug-found/scenario-repaired 路由不变），状态机从 testing 正常推进

#### Scenario: 连续两次查重拒绝升级人工

- **WHEN** 重合成产物再次被查重门拒绝（连续 2 次）
- **THEN** 框架将 spec 置 blocked、error 携带两轮违规摘要，并发送 admin 升级告警
- **THEN** 框架 MUST NOT 无限重试重合成

### Requirement: 重合成定向指令注入

查重拒绝时框架 MUST 写入重合成指令文件（含被拒场景清单、逐场景现有归因文本、归因契约要求），供重合成 prompt 注入。

- 指令 MUST 包含每个被拒场景的失败步骤序号、断言 label 等框架已掌握的场景局部数据，作为归因文本的差异化素材。

#### Scenario: 指令文件驱动差异化改写

- **WHEN** 重合成 judge run 启动
- **THEN** prompt 含指令段：被拒场景清单 + 各场景步骤序号/断言 label 差异化素材 + 「归因文本 MUST 引用本场景局部数据（步骤序号/断言 label/完整 error），MUST NOT 套用共享模板串」契约

### Requirement: judge 归因文本契约（事前预防）

planner-judge prompt MUST 声明归因文本契约：根因与 classification 允许多场景共享，但 `first_failed_step` 与断言 triage evidence MUST 引用本场景自己的步骤序号、断言 label 或完整 error（禁截断致多场景同文、禁模板串）。

#### Scenario: 契约进入裁决事前视野

- **WHEN** planner-judge 被派发裁决
- **THEN** prompt 含归因文本契约段（≤10 行），明确「共享根因合法、归因文本必须逐场景可区分」

### Requirement: 查重归一化细分与级联豁免

`check_batch_attribution_dedup` 的归一化 MUST 纳入场景局部数据（失败步骤序号、断言 label），并实现级联豁免：场景组 classification 相同、归因描述体共享同一根因短语、但失败步骤序号或断言清单逐场景不同 → 不计入查重命中。

- 纯模板偷懒形态（连步骤引用都逐字复制）MUST 仍被拒绝。

#### Scenario: 单根因级联失败不再误拒

- **WHEN** 5 个场景 classification 均为 env、first_failed_step 描述体共享同一根因，但失败步骤序号与断言清单各异
- **THEN** 查重门放行（不判违规）

#### Scenario: 模板偷懒仍被拦截

- **WHEN** 4 个场景的归因归一化后逐字相同（含相同步骤序号与断言引用）
- **THEN** 查重门拒绝并产出违规清单

### Requirement: 原地重试派发前状态复查

agent_runner 的两处原地重试通道（provider-transient 退避、artifact-gate 退避）在重派前 MUST 复查 spec 状态：当前 status 非该 agent 预期态（judge→testing、implementer→implementing）或 frozen / `_cancelled_hold` 时 MUST 放弃重试并返回语义化失败。检查自身异常时 fail-open（保持既有重试语义）。

#### Scenario: admin 接管后重试让位

- **WHEN** judge run 遭 provider-transient 失败进入 30s 退避，期间 admin 将 spec 置 blocked
- **THEN** 退避结束后框架放弃重派（不产生新的 judge run），返回携带让位语义的失败结果
- **THEN** 该轮 token 消耗不再发生（相比 19:48 事故白烧 $4.77）

#### Scenario: 正常退避重试不受影响

- **WHEN** judge run 遭 provider-transient 失败进入退避，期间 spec 仍为 testing
- **THEN** 退避结束后照常原地重试（现状行为保持）

### Requirement: 拒绝语义文案修正

查重拒绝相关日志与注释 MUST 使用「拒绝采纳」语义（report.json 已在盘上，拒绝的是状态机采纳），代码注释 MUST 与实际回路一致（重合成回路存在性的描述）。

#### Scenario: 日志文案可对账

- **WHEN** 查重门拒绝一轮裁决
- **THEN** ERROR/WARNING 日志写「拒绝采纳」而非「拒绝落盘」，且不含「下轮修文后自然通过」类不存在的回路描述
