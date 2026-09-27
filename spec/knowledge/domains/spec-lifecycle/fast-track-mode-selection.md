# 快车道选道判定（模式评估与元数据）
<!-- knowledge: capability=fast-track-mode-selection rev=1
     sources=spec/archive/2026-09-09-add-fast-track-mode -->

立项阶段确定 SPEC 走 fast-track 还是 full：需求 Agent 给出明确建议，用户显式指定优先，模式落元数据供派发选道。

## 规则

- 用户经 `/fenix-new` 创建 SPEC 未指定执行模式时，需求 Agent 必须评估需求复杂度并给出**明确**的模式建议（建议 fast-track 或建议 full）附简要理由，供用户选择；禁止在无建议的情况下默认任一路径。
- 简单需求（单点小改动、影响面小、场景少）建议 fast-track；复杂需求（跨模块、含 UI/迁移、验证场景多）建议 full；给出建议的同时告知用户可选另一模式。
- 用户显式指定执行模式时框架必须尊重，需求 Agent 不得以评估结果覆盖用户选择，不追问、不改写。
- 确认后的执行模式写入 spec 元数据（`mode` 字段），daemon 派发时据此选择路径。
- 元数据无 `mode` 字段的存量 SPEC 按缺省 `full` 处理，行为与无此能力时一致。
- Dashboard 的 spec 列表与详情页展示每个 SPEC 的执行模式标记（fast-track / full）；无 mode 字段的 SPEC 按缺省 full 展示。

## 溯源

- 2026-09-09 2026-09-09-add-fast-track-mode — 新增选道判定：复杂度评估与明确建议、用户显式指定优先、mode 元数据落盘与缺省 full、Dashboard 模式标记
