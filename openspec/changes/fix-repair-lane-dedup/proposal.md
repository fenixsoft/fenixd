# Proposal: fix-repair-lane-dedup

## Why

2026-08-28 实证（fix-improve-failover-model-mapping-ui 系）：fix spec 自身验证失败（bug-found）时，两条修复通道同时激活——通道 A：扫描 recovery 对 bug-found 的 fix spec 重置回 ready 并重派其泛化实现器；通道 B：judge 判定同一份验证报告派生深度+1 的子 fix（带靶向报告上下文）。两通道实现同一批缺陷：轻则顺序重复劳动烧 1-2 小时 token（当日 fix#1 重实现 81 turns 起步即 25 分钟通读零提交），重则并行改同一文件引发 merge 冲突（当日 14:10 app.js 冲突即此模式，直接导致整轮验证白屏假失败的连锁）。

## What Changes

- **守卫一（reset 抑制）**：bug_found 重发/reset 路径上，bug-found 的 fix spec 若已存在同根非终态子 fix，保持 bug-found 不重置——由子 fix 承载修复，子完成后走既有 "Fix done — re-verifying original" 路径。
- **守卫二（spawn 抑制）**：judge 派生路径上，被验对象本身是 fix spec 且其自身处于 ready/implementing（重实现已在飞）时跳过派生，在 error/evidence 注明"由在飞重实现承载"。
- **守卫三（派发互斥）**：调度器派发 fix spec 实现器前检查同根兄弟是否存在活跃实现器/验证器，存在则保持 ready 跳过本轮（防历史双 ready 现场重复派发）。
- 三守卫均为**先到先得、后到抑制**，不偏袒任一通道；无子且无在飞时既有行为完全不变；子 fix 终态后父级重验路径不受守卫误伤。

## Capabilities

### New Capabilities
- `repair-lane-dedup`: 双修复通道（父 fix 重实现 vs judge 派生子 fix）的三级去重守卫

### Modified Capabilities

<!-- 无 -->

## Impact

- **代码**：`core/pm_engine.py`（spec_bug_found 处理器 reset 路径守卫一、judge 派生 spawn 路径守卫二、_process_queue 派发守卫三）、族谱度量函数复用（同根判定）
- **配置**：无新增键
- **测试**：守卫一/二/三单测（先到先得语义、无子无在飞零行为差异、子终态不误伤、双 ready 历史现场不重复派发）
