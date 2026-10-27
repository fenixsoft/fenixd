# Design: fix-frozen-scenario-dict-salvage

## Context

冻结场景文件装载读端位于 `core/pm_engine/verification/pipeline.py` 冻结装载段（读文件 → `json.loads` → 顶层 `isinstance(raw, list)` 检查 → 顶层非数组即 `_escalate_env_blocked`（场景计划争议））。dict 包裹拯救 `_salvage_top_level_dict` 已存在于同文件（evo-scenario-product-toplevel-contract 2.2 交付），其内部走 `core.verify_engine.scenarios.salvage_scenarios_file`：解包 → 重过全部场景校验 → 以纯数组原子重写落地（非仅内存采纳），并返回解包后场景列表；不可拯救返回 None。当前该拯救只被阶段 2 验收归因点调用。

事故实证（add-command-center，2026-10-26 20:46）：verify agent 写出 dict 包裹形态 → 冻结读端 fail-closed → 争议第 2 轮 → 连续 2 轮自动冻结。若冻结读端当时接有拯救，16/18 pass 的场景集当场救活。

## Goals / Non-Goals

**Goals:**
- 冻结装载读端对 dict 包裹形态先解包止损再装载，消除本冻结形态
- 不可拯救路径与接线前逐位一致（fail-closed 人工通道不动摇）

**Non-Goals:**
- 不改 `salvage_scenarios_file` 本体与阶段 2 归因点既有接线
- 不改冻结契约迁移（contract_version）路径
- 不给其他读端（fastlane/verdict_evidence/load_scenarios 等）接拯救——与 evo-scenario-product-toplevel-contract D4 同口径：拯救落地时已原子重写为纯数组，其余读端自然恢复

## Decisions

- **D1 复用单点拯救实现**：冻结读端直接调用既有 `_salvage_top_level_dict`（其内部即 `salvage_scenarios_file`），不写第二份解包实现。拯救成功返回的列表直接作为 `raw` 继续走既有 `frozen_contract_version` 迁移与装载（文件已被拯救原子重写为纯数组，内存与磁盘一致）。
- **D2 接线位置**：置于 `isinstance(raw, list)` 检查内部——顶层非数组时先判「dict 且可拯救」，可拯救则以解包结果替换 raw 继续；不可拯救落回既有 `_escalate_env_blocked` 分支（保留原错误文案与处置选项）。
- **D3 fail-closed 保持**：解包失败（含异常兜底）一律走既有 corrupt → env_blocked，与阶段 2 归因点「解包后仍不合法 MUST 照常拒收」同语义。
- **D4 留痕复用**：拯救成功/不适用日志由 `_salvage_top_level_dict` 既有 WARNING/INFO 落盘，冻结读端不新增日志形态。

## Risks / Trade-offs

- **解包掩盖 agent 违约**：dict 包裹即顶层交付契约违约，解包属一次性止损——该语义已在 evo-scenario-product-toplevel-contract 定调（解包不弱化契约约束，WARNING 留痕可审计），冻结读端沿用同一口径。
- **重写竞态**：拯救的原子重写与并发读者（fastlane 等）理论上有窗口；与阶段 2 归因点既有风险同级，且验证轮内冻结装载与场景消费不并发，风险可接受。
