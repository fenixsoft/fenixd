## Context

2026-10-06 核查：agents/implementer.md 全文 46 行无宿主变更条款（经 core/agent_runner/prompt_builder.py:43 加载、无内置回退）；agents/administrator.md:141 备份留痕仅为模板示例；core/ 无环境变更登记/回滚机制；admin 告警通道 core/admin_store.py 为现有持久台账（本案 idx 88 即经它留痕）。
巡检锚点：dkms status 的「Diff between built and installed module!」WARNING 与 modinfo version 的 -dirty 后缀。
**登记载体实测约束**（spec-review 复核）：击杀类终止（超时/轮次上限/判停 SIGKILL）且无 CLI result 时 result 事件通道失联（core/agent_runner/runner.py「killed_without_cli_result」注记）——被击杀 run 不存在 run-result 文件；且 implementer 在 worktree 执行，`.fenix-run-result.json` 经 `_copyback` 单向拷回主树（runner.py worktree 拷回注记），击杀时拷回同样不发生。本案触发场景即 600 轮击杀，故**登记 MUST 以「变更发生时即时写入的登记文件」为权威载体，run 结果汇总仅为收尾冗余**，否则头牌场景（击杀不丢失）不成立。

## Goals / Non-Goals

- [x] 提示词备份/登记契约 + 失败终态自动告警（登记+告警，不自动执行回滚）
- [ ] 不做自动回滚执行器；不做全量系统快照

## Technical Design

1. agents/implementer.md「约束」节新增宿主变更契约（备份+**变更发生时即时登记**+回滚指引+用户态优先）。
2. agents/administrator.md：处置记录模板将「备份目录/回滚计划」从示例升为破坏性动作 MUST 项。
3. 登记载体：worktree 根 `host_changes.json`（与 `.fenix-run-result.json` 同级，变更发生时增量写，元素含对象路径/版本/备份位置/回滚指引）；加入 `_copyback` 拷回清单使 result-bearing run 落主树留痕。
4. core/agent_runner/runner.py 终态记录点（error/killed/超时/轮次上限/判停统一收尾段，先于 worktree 清理）读取 worktree 根登记文件：终态失败且登记非空 → 调 admin_store 派发；成功终态仅留痕不告警。
5. core/admin_store.py 新增派发方法（severity=major，kind=escalation，append_if_absent 去重键=spec+变更对象路径），复用既有告警生命周期；admin_store 为存储层，不自行感知 run 终态，由 runner 终态路径调用。
6. core/agent_runner/result_gate.py：run-result host_changes 汇总字段校验（警告级 fail-open，字段缺失不拒绝结果）。
7. 防护：告警只增不执行；对无宿主变更的 run 零新增开销（登记文件缺省不存在即跳过）。

## Open Questions

- 宿主污染标记的载体（STATE 字段 vs 告警 summary）——实现时按 admin 侧消费习惯定。