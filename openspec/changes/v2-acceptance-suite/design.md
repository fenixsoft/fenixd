## Context

设计 §7 通过标准:脚本全绿 → 用户人工浏览 /v2/ → 替换(cutover SPEC 单独执行)。测试基建已在 v2-shell-hash-router 落地;双版对比利用并存期:同一脚本对 / 与 /v2/ 跑只读断言。

## Goals / Non-Goals

- Goals: acceptance.spec.js 全绿;RUNBOOK 可让任何人复跑
- Non-Goals: 性能压测;视觉回归(截图 diff)

## Decisions

- **零 pageerror 是硬断言**:全程 page.on('pageerror') 收集,验收脚本结尾断言为空
- **双版对比只读**:只断言列表行数一致、关键元素可见,避免对老版产生写操作
- **fixme 透明化**:环境实况导致跳过的用例在 RUNBOOK 列明原因与前置条件

## Risks / Trade-offs

- 环境数据动态变化,行数对齐用 ≥0 且两版相等的宽松断言
