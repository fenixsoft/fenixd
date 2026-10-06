# 提案：add-adjudication-alert-narrative

## Why

转人工裁决告警的文案当前由发射点用 f-string 机械拼凑（如 `'add-archive-state-migration' 升级闸门连续失败第 4 轮，已冻结等待人工裁决`），evidence 更是原始技术串（`failure_profile=round1:real-bugs; round2:real-bugs; round3:repeat; diff[round1]: added=[...]`）。真实事故（2026-09-29 add-archive-state-migration）中，决策者面对告警无法独立回答三个基本问题——**当下遇到了什么问题、为什么要人工决策、建议的选项各自意味着什么**——只能另行询问 AI 后才敢点「继续自动修复」。

裁决贵在及时；每多一次「先找人问清楚」的中转，冻结窗口就多拉长一段。告警应当自解释。

## What Changes

1. **告警落盘时同步生成三段式叙事**（单一汇聚点接线）：`pm_engine._send_human_escalation_alert`（core/pm_engine/family.py:975）是全部 ESCALATION 告警的共同写入口（预算耗尽/升级闸门/评审两族/judge 重跑上限/同因重派熔断/恢复期回调均汇聚于此），在该处对**携带 choices 的桶 2 真裁决信号**追加 `narrative` 字段——由一次轻量 LLM 调用生成的人类可读说明，三段固定结构：
   - **发生了什么**：现象与关键证据的白话解读（把 failure_profile 等技术串翻译成因果叙述）；
   - **为什么需要你决策**：自动链尝试了什么、为何停（计数器/预算/闸门哪条线到顶）、继续自动的代价是什么；
   - **决策选项**：结合本告警上下文逐一解释每个 choice 的含义、后果与建议倾向。
2. **旁路发射点同覆盖**：不经汇聚点的两个 choices 附带点（core/worktree_manager/mergeback.py:476、core/agent_runner/token_budget.py:257）接入同一叙事辅助模块，覆盖面=全部转人工裁决告警。
3. **失败兜底 fail-open**：LLM 调用失败/超时/开关关闭时，告警照常以现有机械文案落盘（不写 narrative 字段），发射链路零阻塞——叙事是增强，不是门禁。
4. **结构化字段不动**：narrative 只增不改，description/evidence/recommended_action/choices/trigger 的既有语义与消费方（alert-resolve、闭环判定、Administrator）完全不受影响。
5. **前端展示**：告警区在证据之前渲染 narrative 三段式（无该字段时渲染保持现状）；选项下拉的行为不变。
6. **配置与 UI**：新增 `admin.narrative_enabled`（缺省 true）/ `admin.narrative_timeout_seconds`（缺省 60）/ `admin.narrative_model`（缺省复用 admin.agent_model），config.template.yaml 同步注释，设置页 SystemPanel 出三配置项。

## Capabilities

- `adjudication-alert-narrative`：转人工裁决告警的三段式人类可读叙事（生成、接线覆盖面、兜底、展示、配置）。

## Impact

- **改动面**：pm_engine 告警写入口 + 2 个旁路发射点 + 1 个新叙事模块 + 前端告警区/SystemPanel/services 类型 + config.template.yaml + 文档。
- **不做什么**：不改裁决执行链（alert-resolve/Administrator 动词映射）、不改冻结闸门判定逻辑（决定权留在机械闸门）、不给桶 0 知情类告警加叙事、不做异步补叙链路、不改微信推送通道。
- **风险**：LLM 通道依赖现有网关可用性——由 fail-open 兜底；同步调用引入最多 timeout_seconds 的落盘延迟——由开关与超时约束，且仅发生在低频的转人工时刻。
