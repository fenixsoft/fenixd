## Context

2026-10-06 核查：agents/implementer.md 全文 46 行无宿主变更条款（经 core/agent_runner/prompt_builder.py:43 加载、无内置回退）；agents/administrator.md:141 备份留痕仅为模板示例；core/ 无环境变更登记/回滚机制；admin 告警通道 core/admin_store.py 为现有持久台账（本案 idx 88 即经它留痕）。
巡检锚点：dkms status 的「Diff between built and installed module!」WARNING 与 modinfo version 的 -dirty 后缀。

## Goals / Non-Goals

- [x] 提示词备份/登记契约 + 失败终态自动告警（登记+告警，不自动执行回滚）
- [ ] 不做自动回滚执行器；不做全量系统快照

## Technical Design

1. agents/implementer.md「约束」节新增宿主变更契约（备份+登记+回滚指引+用户态优先）。
2. agents/administrator.md：处置记录模板将「备份目录/回滚计划」从示例升为破坏性动作 MUST 项。
3. core/agent_runner/result_gate.py：run-result host_changes 登记字段校验（警告级 fail-open，字段缺失不拒绝结果）。
4. core/admin_store.py：run 终态失败且 host_changes 非空时自动派发回滚义务告警（severity=major，去重键=spec+变更对象路径），复用既有告警生命周期。
5. 防护：告警只增不执行；对无宿主变更的 run 零新增开销（字段缺省空）。

## Open Questions

- 宿主污染标记的载体（STATE 字段 vs 告警 summary）——实现时按 admin 侧消费习惯定。