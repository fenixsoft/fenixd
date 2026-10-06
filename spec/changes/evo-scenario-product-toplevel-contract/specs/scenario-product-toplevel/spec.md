# scenario-product-toplevel Specification

## Purpose

场景规划产物 test_scenarios.json 的顶层形状成为显式交付契约；验收器拒收时按失败类别给最小修复路径，杜绝「一层包裹错误放大成 25 场景全量重建」的浪费形态。

## Requirements

### Requirement: 规划任务书顶层契约

planner-plan 的交付要求 MUST 显式声明 test_scenarios.json 顶层为纯 JSON 数组、禁止 {"scenarios":[…]} 之类 dict 包裹，MUST 附正反例各一行，并 MUST 显式区分同目录 scenarios.json（持久化集，dict 形态）的形状差异；该契约还 MUST 经 prompt_builder 场景 schema 段单源注入运行时提示词（仅 planner-plan 会话生效）。

#### Scenario: 运行时提示词含顶层契约

- **WHEN** 构造 planner-plan 会话提示词
- **THEN** 注入内容含「顶层必须是纯 JSON 数组」契约句、dict 包裹反例与 scenarios.json dict 形态区分说明

#### Scenario: 其他 agent 不受影响

- **WHEN** 构造 planner-judge 等非 planner-plan 会话提示词
- **THEN** 不注入该顶层契约条目，既有内容不变

### Requirement: 可拯救形态机械解包

验收器对顶层非数组的 test_scenarios.json MUST 先尝试机械拯救：顶层为 dict 且含 scenarios 数组时，解包后按既有全部场景校验重验，通过则以解包后的纯数组原子重写 test_scenarios.json（落地非仅内存采纳，保证其余读端与冻结层顶层读端按既有语义恢复）并留痕（记录解包前顶层键与条目数）；解包后仍不合法 MUST 照常拒收，其余非数组顶层不拯救。拯救 MUST 仅接入验收归因路径单点，其余 load_scenarios 读端不接助手。

#### Scenario: dict 包裹产物被解包采纳

- **WHEN** test_scenarios.json 顶层为 {"scenarios":[…]} 且解包后通过全部场景校验
- **THEN** 以解包后的纯数组原子重写 test_scenarios.json 并通过验收，留解包留痕，不触发重派，且其余读端（fastlane/verdict_evidence/冻结装载）与冻结层顶层读端后续按既有语义可见纯数组

#### Scenario: 解包后仍非法照常拒收

- **WHEN** 解包得到的数组未通过既有校验，或顶层 dict 不含 scenarios 数组
- **THEN** 按原错误拒收，不落地

### Requirement: 拒收反馈按类别给最小修复指引

REPLAN_FEEDBACK 的场景文件拒收文案 MUST 按失败类别生成：格式类（顶层形状/条目结构）给「最小修复」指引（指明错误类别与修复动作），MUST NOT 一律硬编码「重新输出全部场景」；内容类缺失仍可指示全量重建。

#### Scenario: 格式类失败给最小修复指引

- **WHEN** 验收器以格式类错误拒收场景文件
- **THEN** 反馈文案指明错误类别与最小修复动作，不含「重新输出全部场景」

#### Scenario: 内容类缺失保留全量重建指示

- **WHEN** 拒收原因是场景定义内容缺失（如场景整体缺失）
- **THEN** 反馈文案可指示全量重建，既有行为不回归