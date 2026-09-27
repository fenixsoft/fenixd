# ADR-123：验证裁决单源读取，共享结果文件按 role 戳标注

date: 2026-09-19
status: accepted

## Context

主树共享 `.fenix-run-result.json` 被全部 agent 类型无条件覆盖拷回，verdict 读取路径散点多处、回退判据依赖 run_id 可解析——implementer 残留的 success 会被当成验证裁决消费（裁决污染），且陈旧判定在 run_id 形态不符时静默失效（不判陈旧）。

## Decision

- 主树共享结果文件的唯一写入者是 runner 拷回点：拷回时按 agent_type 注入 role 与 spec 戳；role 取值为实际写者全集（implementer/verifier/planner/judge/repair），缺 role 视为旧格式遗留。
- 裁决读取收敛单一入口：per-spec 证据文件优先（ADR-082 口径），回退共享文件时**先验 role/spec 戳**、不依赖 run_id 可解析；裁决读路径命中 role≠verifier 的共享文件 → 记 deliverable-dispute 而非当作裁决消费。
- 戳校验的丢弃仅限裁决读路径：实现结论、planner 兼容回退等合法消费同一共享文件的读取方不受影响。

## Consequences

- 跨角色污染在读取口被结构性拦截；新 agent 类型接入时必须在写者全集内登记 role，否则其产物对裁决通道不可见（fail-closed）。
