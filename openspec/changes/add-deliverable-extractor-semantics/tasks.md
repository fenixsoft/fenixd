# Tasks: add-deliverable-extractor-semantics

实现依据（实施 agent 必读）：
- 能力定义 `specs/implementer-deliverable-gate/spec.md`（MODIFIED）；设计决策 design.md D1-D4
- 现状代码：`.fenix/core/deliverables.py`（extract_paths）、`.fenix/core/pm_engine.py` `_deliverable_gate_missing`（约 3491-3511 行，含热修 4461231 的内联归一化——本次下沉）
- 真实夹具：`openspec/changes/add-interaction-contract-and-per-assert-triage/tasks.md`（引用语境样本）与分支 `fenix/add-interaction-contract-and-per-assert-triage-1788091910`

## 1. 提取器升级

- [ ] 1.1 新增 `extract_paths_typed(spec_dir) -> {"deliverables": [...], "references": [...]}`：按 D1 语境规则表分类（tasks 说明段/引用关键词 → references；勾选行/新增动词 → deliverables；proposal 仅交付语境）；无法判定归 deliverables
- [ ] 1.2 旧 `extract_paths` 改为兼容包装（deliverables + references 拼接去重），既有调用方与测试不破坏
- [ ] 1.3 `normalize_check_path(p)` 纯函数：`.fenix/` 前缀归一化（下沉热修 4461231 内联逻辑）

## 2. 守卫接入

- [ ] 2.1 `_deliverable_gate_missing` 改用 typed 提取 + normalize_check_path；references 缺失 → `logger.warning("deliverable-reference-missing")` 仅留痕，不产生缺件
- [ ] 2.2 移除调用点内联归一化（逻辑单点化）

## 3. 单元测试

- [ ] 3.1 覆盖：引用语境不阻断（interaction-contract tasks 真实样本，4 路径归 references）；交付语境缺件仍阻断；无法判定保守归 deliverables；归一化复检（真实分支夹具，复现 4461231 行为）；引用缺失仅审计
- [ ] 3.2 旧 `extract_paths` 兼容包装行为不变（既有测试全过）

## 4. 验证与打包

- [ ] 4.1 运行 `python3 -m pytest tests/ -v` 确认无回归
- [ ] 4.2 执行 `bash scripts/package.sh` 生成最新扩展包
