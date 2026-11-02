## Why

知识蒸馏当前由 SPEC 归档移动触发（`commit_archive_move` 单点漏斗），而归档滞后于交付——日常主力是 R2/R3 时效归档（终态滞留 ≥3 天），导致 SPEC 从 push 到知识页产出平均延迟 3 天以上。pushed 才是交付确认点（终态、内容不再变），蒸馏应紧跟交付节奏：SPEC 转移到 pushed 状态即触发蒸馏。

## What Changes

- **触发点迁移**：`PmEngine.approve_push`（done→pushed 单点写点，人工 fenix-approve 与自动审批 `_auto_approve` 双路汇聚，自带幂等守卫）成功转移后 fail-open 派发 `dispatch_distill`；`commit_archive_move` 的蒸馏挂载移除（无双触发）。
- **输入目录切换**：门控存在性检查与蒸馏 prompt 输入路径从 `spec/archive/<名>` 切到 `spec/changes/<名>`（push 触发时 SPEC 未归档、恒在 changes/）；pending 台账恢复重派路径按 changes/ 优先、archive/ 兜底双态探测（push 后 3 天内失败的批，恢复时可能已归档）。
- **溯源契约衔接（归档改写 pass）**：蒸馏模板与知识页溯源链接改指 `spec/changes/<名>/`；归档移动成功后的单点新增知识页溯源改写 pass（该 SPEC 的链接/sources 批量改写到 `spec/archive/<date-name>/`），并入归档提交——知识页链接任何时刻指向真实存在的路径，validate/audit 链接门两态自洽。
- **语义收窄（声明）**：done 未 push 的 SPEC 永不蒸馏（push=交付确认）；蒸馏失败批的 pending 恢复重派兜底保留。

## Capabilities

### New Capabilities
- `distill-push-trigger`: 知识蒸馏的 push 触发契约——approve_push 单点派发、fail-open、幂等边界、输入目录双态解析、归档改写 pass 与溯源链接两态自洽。

### Modified Capabilities
<!-- distill-run-artifacts（本仓 spec/changes/ 活跃）：其 Requirement 锚定
     「蒸馏批次产出 run 产物」的批生命周期语义，不随触发源变化——批入口
     _run_batch 与产物写侧正交，无需 delta。已在归档目录核查无其他同族能力。 -->

## Impact

- **触发写点**：`core/pm_engine/engine.py`（approve_push 派发挂载）；`core/archive_commit.py`（移除蒸馏挂载，三路归档漏斗同删）。
- **蒸馏链路**：`core/knowledge.py`（`_gate_distill` 存在性检查参数化、`build_distill_prompt` 输入路径、`recover_pending` 双态探测）；`core/knowledge_prompts/distill.md`（语境与溯源契约段）。
- **归档链路**：归档移动成功后的单点（`bin/fenix_archive.py` 与 `core/dashboard/data/spec_archive.py` 双路径须同覆盖）新增溯源改写 pass，并核查 `core/knowledge_audit.py` 溯源检查的路径锚定兼容两态。
- **正交不受影响**：run 产物写侧（add-distill-run-artifacts 的 `_run_batch` 包装与触发源无关，自动工作）；回填期排队门、flock 单飞、队列合并、修正轮语义全部保留。
- **风险面**：知识审计链接门为本仓已知痛点（`_check_links` 与 distill 溯源契约互斥史），改写 pass 缺位会让归档后知识页出现死链——改写必须 fail-open 告警留痕，不静默。
