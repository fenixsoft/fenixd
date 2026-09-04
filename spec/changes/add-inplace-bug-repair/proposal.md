# Proposal: add-inplace-bug-repair

## Why

bug-found 处置目前自动派生 `fix-*` 子 SPEC，本质是一次**有损压缩**：自动生成的 proposal/tasks 只有两行引用，丢失父 SPEC 的 design 决策与任务上下文，implementer 被迫重复诊断（v2-shell-hash-router 事故实测 24+ 分钟）。派生机制还派生了三个已花费治理成本的副产品：fix 族谱爆炸（四层嵌套实测）、重复派发（已由 pushed 的 fix-repair-lane-dedup 三守卫治理）、报告引用断裂（已由在途 add-verify-report-gate 治理）。原地打回保留全部上下文，且让上述治理面整体消失。

## What Changes

- **bug-found 处置改为原地打回**：验证裁决认定真实产品缺陷后，不再派生 fix SPEC；改为递增父 SPEC 的失败轮数计数器、将父 SPEC 重置回 `implementing`、并在其 tasks.md 追加「验证修复」任务段（引用 `verification-report.md`，存在性由 add-verify-report-gate 保障）——随后由正常派发循环接管实现与重验。
- **升级闸门**：同一 SPEC 验证失败轮数达到阈值（模块常量 3）→ 冻结为 `blocked` 并发 human-escalation-alerts 告警，停止自动修复，等待人工裁决。
- **fix 派生路径退役**：bug-found 不再创建 fix-* SPEC；既有 fix 族谱收敛 governor（fix-family-convergence-governor，随 improve-scheduling-noise-governance 已 pushed）与派发级互斥（fix-repair-lane-dedup，已 pushed）随派生路径消失而失去作用对象，相关死代码随本变更清理。
- **既有 fix 链兼容**：已存在的 fix-* SPEC（如 fix-v2-shell-hash-router）跑完自然终态；「子 fix 完成 → 父 SPEC 自动重验」闭环保留，仅对存量链条生效。
- 取代关系：本变更使 fix-repair-lane-dedup 与 improve-scheduling-noise-governance 的 fix-family-convergence-governor 能力退役（两者均已 pushed，无在途派发可撤回）。

## Capabilities

### New Capabilities
- `inplace-bug-repair`: bug-found 的原地打回处置——失败轮数计数、状态重置与修复任务注入、升级冻结闸门。

### Modified Capabilities
- `verification-completion-gate`: 「失败场景噪音与缺陷分流」中真实产品缺陷的处置由「派生 fix SPEC」改为「原地打回父 SPEC」；噪音分流与 fail-closed 语义不变。

## Impact

- **代码**：`.fenix/core/pm_engine.py`（bug-found 处置分支、派生路径退役）、`.fenix/core/state_machine.py`（`_verify_fail_rounds` 内部字段持久化）
- **行为**：验证失败 → 父 SPEC 自身回炉，上下文零丢失；族谱不再增长
- **成本**：消除 fix 派生的信息重建消耗；消除族谱/重复派发两类治理开销
- **风险**：无限修复循环（由轮数阈值+冻结拦截）；存量 fix 链与新机制并存的过渡期语义（保留 legacy 闭环，互不干扰）
