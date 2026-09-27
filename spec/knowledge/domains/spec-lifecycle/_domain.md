# SPEC 生命周期

SPEC 生命周期。本域能力条目清单如下（能力页由存量回填批次逐步产出，落盘后此处升级为链接）。

## 能力页

- `approve-mode` — 审批模式（人工审批门开关）
- `draft-promotion-gate` — 草稿 drafted→ready 晋升门控
- `manual-spec-promotion` — SPEC 手工晋升
- `spec-review-gate` — 方案评审门（reviewing 状态）
- `spec-review-agent` — 方案评审 agent
- `spec-review-recovery` — 评审车道中断恢复
- `spec-review-rejection-schema` — 评审拒绝结果的结构化模式
- `spec-manual-activation` — SPEC 手工激活
- `scheduled-spec-pickup` — SPEC 定时拾取（start_after）
- `scheduled-spec-unfreeze` — SPEC 定时解冻
- `start-after-scope-config` — start_after 拾取范围配置
- `spec-concurrency-governance` — 同 SPEC 在飞并发治理
- `spec-content-integrity-gate` — SPEC 内容完整性门
- `spec-event-hooks` — SPEC 事件钩子
- `spec-archive` — SPEC 归档（手动/查询/自动）
- `auto-spec-archive` — SPEC 自动归档
- `archive-auto-commit` — 归档产物自动提交
- `fast-track-mode` — 快车道执行模式
- `fast-track-mode-selection` — 快车道选道判定
- `fast-track-scale-precheck` — 快车道规模预检
- [spec-lifecycle-state-model](spec-lifecycle-state-model.md) — SPEC 生命周期状态机与 STATE.md 原子读写
