# CR 正确性缺陷修复批

<!-- knowledge: capability=correctness rev=2
     sources=spec/archive/fix-cr-correctness-1789899983,spec/archive/fix-cr-correctness-524b59-1789899988 -->

面向代码审查台账 correctness 类条目的专项修复批：从台账选中问题逐条修复并核销。

## 规则

- 批范围由 code-review 台账选中的 correctness 类条目决定，批 delta 逐条登记问题描述、严重度与证据位置，修复只针对选中条目。
- 验收口径：修复提交后对应问题不再出现在 code-review open 列表。
- 批内容随台账选中集变化，本页不固化具体条目清单；各批修点见溯源。

## 溯源

- 2026-09-20 fix-cr-correctness-1789899983 — 首批修复 5 处选中问题：全仓核销空集保护字段取错、SSE cleanup 未重置增量刷新定时器、切换项目未重置提示词面板 activeAgent、队列锁非可重入自死锁、边界类失败回流致无限递归。
- 2026-09-20 fix-cr-correctness-524b59-1789899988 — 第二批修复 10 处选中问题：fixture 基线提交返回码未检与非原子写、`shutdown_drain_seconds: 0` 真值回落、keep-alive 早期返回未排空请求体、在飞去重按子串误匹配、`/proc/net/tcp` 截断行 IndexError、QualityTab 死代码 SSE 分支、summary 字段缺失误删列表行、三态回读 null/undefined 错配、loadConfig 无取消守卫。
