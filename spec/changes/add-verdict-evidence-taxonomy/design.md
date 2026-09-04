# Design: add-verdict-evidence-taxonomy

## Context

裁决链：场景执行器产出 step/assertion 结果 → planner-judge 汇总裁决 → `parse_verdict`（dashboard/data.py）与合成器消费。现状问题（v2-config-page 00:14 报告实证）：11 个 warning 无分类依据；3 个 failed 场景的 assertion_results 为空（证据只散落在合成 md 里）；warning 可无限重复。noise 分流（「真实产品 Bug」判定）已在 improve-verify-adjudication 落地，但未强制到每个场景、未要求证据结构化。

## Goals / Non-Goals

- Goals：分类强制 + 证据结构化 + warning 收敛升级；报告合成与 parse_verdict 消费兼容
- Non-Goals：不重跑场景（flaky 复跑是场景执行器既有能力，不改）；不引入新状态机状态；不改场景集管理（另一 SPEC 负责）

## Decisions

### D1 分类字段落在场景条目，裁决 prompt 强制输出
planner-judge 输出 JSON 的每个场景增加 `classification` 与 `evidence`。裁决 prompt 更新：非 PASS 必须四选一并给证据（从场景执行的 step/assertion 结果中摘取）。校验器（纯 Python）校验字段齐全性与「分类→状态」映射（D3），不合规触发重试。

### D2 校验器独立于裁决（与 scenario-freeze 同型）
`.fenix/core/verdict_check.py`：输入裁决 JSON，校验 classification 合法、evidence 非空、分类-状态映射一致。失败 → 复用既有裁决重试路径一次；二次失败 → blocked-env + 告警（宁可不推进也不带病采纳——与 verify-report-gate 的阻断语义一致）。

### D3 分类-状态映射在采纳处强制重写
裁决采纳点（pm_engine 验证结果处理）按映射表修正 status：product-bug/test-defect → failed。若裁决给了 warning 但分类是 product-bug，以分类为准强制 failed 并在报告标注「已修正」。防止 LLM 输出漂移悬置产品缺陷。

### D4 warning 连续性追踪用 verify-progress 侧车文件
`.fenix/verify-progress/<spec>/warning_streaks.json` 记录 {scenario_id: 连续轮数}，裁决采纳处更新；达 2 → `_send_human_escalation_alert(signal_type="warning_stale_triage")`。场景转 PASS/failed 时计数清零。

### D5 优先复核清单传递
升级告警同时把场景写入下一轮 planner prompt 的「优先复核」注入（与 scenario-freeze 的基准集注入同一接入点，避免两处 prompt 改造）。

## Risks / Trade-offs

- 裁决输出合规率下降会触发重试（每轮多一次 judge 调用 ~0.5M input）→ 仅在字段缺失时重试，合规后零成本；比带病采纳后的人工考古便宜
- flaky 判定滥用（把真缺陷标 flaky 悬置）→ 分类-状态映射管不住这个，但 warning_streaks 2 轮升级兜底 + 告警含证据摘要供人工快速甄别
- blocked-env 二次失败路径可能在网关抖动时误伤 → 与既有「unrecognized_model 网关瞬时故障」经验对齐：重试间隔复用既有退避，不额外加码

## Migration Plan

1. verdict_check.py + 裁决 prompt 更新 + 采纳处映射重写（一次提交）
2. warning_streaks 侧车 + 升级告警接入
3. parse_verdict/合成器兼容新字段（向后兼容：缺字段按旧逻辑）
无配置变更、无数据迁移（旧 report.json 无新字段照常解析）。

## Open Questions

（无）
