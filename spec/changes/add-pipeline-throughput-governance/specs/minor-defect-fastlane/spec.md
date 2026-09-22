# minor-defect-fastlane 能力增量（add-pipeline-throughput-governance）

> bug-found 小缺陷轻量通道契约：三条件阈值（单场景失败 + 影响面 ≤3 文件 + 无 judge 争议）全满足时走 code-fix 轻量车道 + 子集重验，否则回落整轮 fix SPEC 路径。

## ADDED Requirements

### Requirement: fastlane 判定阈值（三条件全满足）

验证轮判定 bug-found 时，验证管线 MUST 评估三个条件：①本轮失败场景数 = 1；②judge 归因的修复影响面 ≤3 文件；③judge 无争议/裁决标记（判据从实现/验证结果文件 findings 的 dispute/adjudication 类条目读取，先例 `branch_guard._disputed_deliverables`；信号机制缺失或无条目时按「无争议」fail-open 并在判定记录留痕）。三条件全部满足 MUST 走 fastlane：生成 code-fix 轻量修复任务（`agents/code-fix.md` 车道）并对其成果仅执行子集重验；任一条件不满足 MUST 走既有 bug-found→fix SPEC 整轮路径（行为与现状一致）。判定过程与所选路径 MUST 记录在验证产物或日志中（可追溯为何走/不走 fastlane）。

#### Scenario: 单场景小缺陷走 fastlane

- **WHEN** 某验证轮 20 个场景中恰 1 个失败（该场景无下游依赖），judge 归因修复涉及 2 个文件，无争议标记
- **THEN** 不派生 fix SPEC，生成 code-fix 轻量修复任务；修复完成后仅重跑该失败场景及其 `depends_on` 前置链

#### Scenario: 多场景失败回落整轮

- **WHEN** 某验证轮 3 个场景失败
- **THEN** 走既有 bug-found→fix SPEC 整轮路径，与未引入本能力前行为一致

### Requirement: 子集重验与回落保护

fastlane 修复完成后的重验场景集 MUST = 失败场景 ∪ 其 `depends_on` 前置依赖链（递归）∪ 以失败场景为前置的下游场景（递归，防修复波及依赖方而漏验），其余通过场景本轮不重复执行（重验报告含全部场景判定，未实跑者沿用上一轮通过结论并标注来源）。fastlane 修复轮次 MUST 计入该 spec 既有验证轮预算；同一验证轮内连续 2 次 fastlane 修复后子集重验仍失败 MUST 强制回落整轮 fix SPEC 路径（防轻量通道打转）。子集重验 MUST 独立可用（不依赖 verdict 缓存能力合入：直接以子集场景集作为本轮执行集）。

#### Scenario: 子集重验通过即收敛

- **WHEN** fastlane 修复完成，子集（失败场景 + 1 个前置场景，共 2 个）重验全部通过
- **THEN** 验证轮按通过收敛，报告含全部 20 个场景判定（2 实跑 + 18 沿用上一轮通过结论并标注来源），不派生 fix SPEC

#### Scenario: 连续两次 fastlane 失败强制回落

- **WHEN** 同一验证轮内第 2 次 fastlane 修复后子集重验仍失败
- **THEN** 不再发起第 3 次 fastlane，转既有 bug-found→fix SPEC 整轮路径，已消耗的修复轮次计入预算

#### Scenario: fastlane 修复不豁免审查门

- **WHEN** fastlane 修复产生代码 diff
- **THEN** 该 diff 按既有 impl-code-review-gate/交付物门禁语义接受审查（不因走轻量通道而豁免任何门）
