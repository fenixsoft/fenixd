# ADR-034：bug 修复原地打回，不再派生 fix-* 子 SPEC

date: 2026-09-05
status: superseded
Superseded by: ADR-075(bug 修复方式配置化双模式，名称前缀分流退役)

## Context

bug-found 处置原先由 pm_engine 自动派生 `fix-*` 子 SPEC（最小 proposal/tasks），implementer 在新 worktree 凭两行引用重建上下文。围绕「派生」这一动作已堆叠多重治理：通道先到先得去重、族谱深度/宽度硬上限、派生入口校验——治理成本持续增长而父 SPEC 目录本身携带全量上下文，派生是信息重建成本的来源。

## Decision

- bug-found 一律原地打回：重置父 SPEC 为 implementing，复用既有派发循环在原 SPEC 内修复；不新建 fix-* 子 SPEC，族谱不再增长。
- 打回只作用于验证 lane 中的未终态 SPEC；done/pushed 后被其它变更暴露的回归属独立缺陷，走新 SPEC 流程，不适用打回。
- 升级闸门用内部计数器 `_verify_fail_rounds`（`_` 前缀字段随状态机跨重启持久化），连续 3 轮验证失败升级人工；阈值为模块常量不进 config，不触发「新增配置键必须带界面」约束。
- 修复任务以 tasks.md 末尾「## 验证修复」追加段注入（引用报告路径 + 轮数注记），既有任务与勾选状态不改写；重验通过后残留无害，不做反向清理。
- 存量派生链自然耗尽前保留 legacy 闭环路径；派生相关代码（`_ensure_fix_spec_files`、族谱 governor）在 legacy 无残留可达后移除。
- 修复通道去重与族谱上限治理随派生路径退役而失去作用对象，ADR-019 据此标记 superseded。

## Consequences

- 修复上下文零丢失（design/proposal/tasks/验证报告同处），机制面整体收缩，无新增派生治理需求。
- 修复迭代台账从族谱可见性退化为「计数器 + tasks 轮数注记 + Dashboard error/status 展示」补偿。
- 父 SPEC 回炉自然暂停其下游依赖推进（依赖判定只看父是否终态），语义正确，无需额外处理。
