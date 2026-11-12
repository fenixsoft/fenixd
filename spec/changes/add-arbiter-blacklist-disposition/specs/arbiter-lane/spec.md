# arbiter-lane Specification

## MODIFIED Requirements

### Requirement: 自主处置白名单

Arbiter 处置模型为黑名单制：禁项外默认可救，处置能力由禁项单源（`core/pm_engine/arbiter_blacklist.py`，B1–B5，见能力 arbiter-blacklist-disposition）枚举约束。可自主处置面：①坏产物拯救（加载器校验失败+归属查证非 planner 产物→删除+显式 status 解冻，既有形态不变）；②验证侧计数冻结复位（随解冻框架附带完成，既有形态不变）；③worktree 陈锁清扫与无主产物清理（`cleanup_paths` 框架白名单校验，既有形态不变）；④预算豁免拍板动作面（写 spec 预算 override 字段+台账留痕，由本能力承接的 add-escalation-chain-admin-arbiter 动作面不变）；⑤T1 场景鲁棒性修复与 T2 稳态复跑探针（经证明器门与 resolved 硬门，见能力 arbiter-blacklist-disposition）。禁项面（MUST 只产裁决包）：生产账本副作用（B1）、人工裁决通道代行——含裁决落位/verdict 缺失终审与 WIP 门分拣提交（B2）、破坏性动作直执（B3）、验证契约放宽（B4）、越界写（B5）；dead-man/停机类维持永久单次直接上升人工（配额复位不适用）。提示词红线 2 修订：Arbiter 可写文件面为 `{report_path}` ∪ 经证明器门获准的场景文件成对写（`_scenarios_full.json`+`test_scenarios.json` 同契约版本戳），其余「看起来像框架产出」的文件一律禁写。白名单外判断反例段废止，替换为黑名单禁项段（判定焦点由"是否在白名单内"反转为"是否命中禁项"）。同签名自主处置受配额治理不变（复现配额 2 次/签名、复位窗 7 天或 spec 状态迁移；dead-man 维持永久单次）。

#### Scenario: 无主坏产物拯救

- **WHEN** 冻结现场的场景文件无法通过加载器校验且归属查证为非 planner 产物（如 verifier 杂交写回）
- **THEN** Arbiter 删除该文件、显式 status 解冻、触发重出题/重验，spec 恢复流转

#### Scenario: 黑名单域内救回取代升级

- **WHEN** 冻结因场景断言失配（如位置点击串扰、选择器锚定不存在类名）且修复在 T1 白名单内
- **THEN** Arbiter 应用修复经证明器门，resolved 附 scenario_fix 证据，spec 恢复流转，人工零感知

#### Scenario: 禁项命中产裁决包

- **WHEN** 处置需消费人工裁决包（judge_rerun_cap 裁决包终审）或放宽验证契约
- **THEN** Arbiter 仅产裁决包（报告+选项+推荐），不改变 spec 状态

#### Scenario: dead-man 类配额例外

- **WHEN** dead-man/停机类签名曾被自主处置、复位窗过后同签名再次触发
- **THEN** 不再自主处置，直接上升人工（永久单次语义，配额复位不适用）

### Requirement: 调查报告与处置台账

每次 Arbiter 调查（无论处置还是升级）SHALL 产出调查报告并落处置台账：五段结构（现场快照/取证时间轴/根因/处置动作或升级理由/证据回链），报告回链归档转录、STATE 条目、git 证据等来源。报告契约 SHALL 扩展救回证据字段：`rescue_evidence`（救回证据类数组：`scenario_fix`｜`probe_transient`｜`artifact_rescue`｜`counter_reset`｜`cleanup`，resolved 时必填且至少一类有效）；`scenario_fixes`（场景修复清单：文件路径+修复类+证明器判定摘要，scenario_fix 证据时必填）。硬门拒绝降级时 SHALL 在台账记录降级事件（原 outcome、命中禁项编号或证明器判定、降级后终态），报告本体不删改。

#### Scenario: 处置台账完整

- **WHEN** Arbiter 完成一次自主处置
- **THEN** 台账新增五段完整条目，含处置前后状态、救回证据类与证据路径回链

#### Scenario: 场景修复报告带证明器摘要

- **WHEN** Arbiter 以 T1 修复场景文件并申报 resolved
- **THEN** 报告 `scenario_fixes` 含逐文件修复类与证明器判定摘要，硬门可机械复核

#### Scenario: 降级留痕

- **WHEN** resolved 报告缺有效救回证据被硬门降级
- **THEN** 台账记录降级事件（原 outcome=resolved、降级原因、终态 escalate），报告原样转裁决包
