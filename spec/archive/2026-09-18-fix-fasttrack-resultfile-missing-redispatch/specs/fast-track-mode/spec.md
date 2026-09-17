# fast-track-mode 增量规格（结果文件缺失不再一律重派）

## MODIFIED Requirements

### Requirement: 统一结果文件驱动状态推进

fast-track agent MUST NOT 直接操作状态机。run 结束时输出统一结果文件（含实现产物清单、设计场景、逐场景验证结果、最终判定），daemon 读取并校验该文件后推进状态转换。

#### Scenario: 结果合法则推进
- **WHEN** fast-track run 结束且统一结果文件通过框架校验
- **THEN** daemon 依据结果文件内容推进状态（判定通过 → verified；存在未修复 bug → 按 bug 处理路径）

#### Scenario: 结果文件缺失且分支有提交则 merge 后补验证
- **WHEN** fast-track run 正常收工（exit 0，`result.success` 为真、`result.branch` 非空）但统一结果文件缺失，且实现分支相对 main 已有提交（`git rev-list --count main..branch` > 0）
- **THEN** daemon 不判该 run 死亡：不回退预算、不 reset ready、不重派实现
- **AND** merge 实现分支（复用 `_reconcile_and_merge`）
- **AND** 改写 `.spec.yaml` mode 为 full 并 enqueue 完整模式 verifier 补齐缺失的 verdict（复用 `_escalate_to_full_mode` 升级语义，触发因不同），后续走既有 verified→done 门
- **AND** 在 spec entry 中记录「结果文件缺失，分支已提交，升级补验证」的原因

#### Scenario: 结果文件缺失且分支零提交或无 branch 则重派
- **WHEN** fast-track run 结束但统一结果文件缺失，且（分支相对 main 零提交，或 `result.branch` 为空即失败/中断 run）
- **THEN** daemon 维持现状：判死亡豁免预算 + reset ready + 自动重派 fast-track run，并在 spec entry 中记录原因

#### Scenario: 结果文件格式非法或未通过硬校验则重派
- **WHEN** fast-track run 结束且结果文件存在，但格式非法或未通过框架硬校验
- **THEN** daemon 维持现状：不推进状态，按失败处理（重派或累计 fail 计数），并在 spec entry 中记录原因