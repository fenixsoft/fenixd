## ADDED Requirements

### Requirement: fastlane 载具修复条目注入
经 fastlane 派发的 code-fix 载具 MUST 携带由失败场景转单的非空修复条目清单；条目为空且存在失败场景时 MUST 出告警留痕，不得静默空转。

#### Scenario: 派发携带非空条目
- **WHEN** 升级闸门前（或既有 minor-defect 路径）派发 fastlane 定向修复
- **THEN** code-fix 载具 prompt 中的 items 为失败场景（场景 ID/涉及文件）转单结果且非空

#### Scenario: 空清单告警留痕
- **WHEN** prompt 构建发现 items 为空但派发方（fastlane）经 detail 顶层键声明存在待修失败场景
- **THEN** 记 WARNING 留痕并可追溯，不再无声注入空清单

### Requirement: 冻结前定向修复分流
升级闸门达到冻结阈值前，对「失败场景数 ≤3 且 judge 根因行级定位」的 product-bug 形态 MUST 先派一轮定向修复（复用 fastlane 载具）并重验，修不过再冻结升级；同一次失败事件已由 minor-defect fastlane 承接派发过 code-fix 的 MUST NOT 再进入分流重复派发（承接与分流互斥）。

#### Scenario: 满足分流形态先修后冻
- **WHEN** 验证失败形态为少量 product-bug 且根因行级定位
- **THEN** 先派定向修复并重验，仅当修复后仍失败才计入冻结计数

#### Scenario: 不满足形态按原阈值冻结
- **WHEN** 失败场景数超阈值或根因非行级定位
- **THEN** 维持现行冻结升级行为不变

#### Scenario: 承接已处置事件不重复分流
- **WHEN** 同一失败事件已由既有 minor-defect fastlane 承接派发过 code-fix 并回落
- **THEN** 该事件不再进入冻结前分流，按既有记账路径推进冻结计数

### Requirement: 升级告警根因注入
升级告警的 recommended_action MUST 包含验证报告的行级根因摘要与裁决指引，既有结构化裁决选项保留。

#### Scenario: 告警携带根因
- **WHEN** 升级闸门挂出 verify_fail_escalation 告警
- **THEN** recommended_action 含失败场景行级根因与「修复重验/豁免」裁决指引