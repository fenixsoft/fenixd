# Proposal: add-deliverable-extractor-semantics

## Why

交付物守卫在 add-interaction-contract-and-per-assert-triage 上连续 4 轮误伤（2026-08-30 复盘）：提取器把 tasks.md「实现依据」段的**既有框架文件引用**（`.fenix/core/*.py`）当作必须新建的交付物，叠加 `.fenix` 自引用符号链接在 git 分支树中不可按树查找，导致每次实现成功都被判缺件、无限重派，累计浪费 ~2 小时 agent 时间与 ~40M input tokens。热修 4461231（`.fenix/` 前缀归一化复检）已止血，但提取器语义（引用 vs 交付物）未区分，同类误伤风险仍在。

## What Changes

- 提取器输出升级为结构化两类：`deliverables`（新建交付物，参与缺件判定）与 `references`（既有文件引用，不参与缺件判定）
- 分类规则：路径出现在「新增/创建/添加」动词上下文或 tasks 勾选项正文中的为交付物；出现在「实现依据/挂钩点/插入点/真实夹具」等引导段下的为引用；无法判定时保守归为交付物
- **正式化 `.fenix/` 前缀归一化**（热修 4461231 的行为）：以 .fenix/ 为前缀的路径按去除前缀后的根路径在分支校验，补齐单元测试与回归夹具（此前热修无测试覆盖）
- 引用类路径改为**软校验**：引用路径若在分支中不存在仅记审计日志，不阻断 merge

## Capabilities

### New Capabilities
（无——扩展既有能力）

### Modified Capabilities
- `implementer-deliverable-gate`：提取器结构化输出与分类规则、`.fenix/` 归一化正式化、引用类软校验（源自 add-implementer-deliverable-gate 变更，能力 spec 见 spec/changes/add-implementer-deliverable-gate/specs/）
