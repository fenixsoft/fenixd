# 设计：保留清理 pending 配额豁免

## 决策背景：修订既有显式决策

「清理不设状态门」是 2026-09-19-evo-item-retention-doc-tracking 归档 SPEC 中记录在案的用户显式决策（其 design.md 第 8 行「用户决策：清理一刀切全状态（不保护 pending/analyzed 等未决条目）」、第 74 行风险表「用户明确选择一刀切全状态；7 天/100 条并集对未决条目是很宽的窗口」）。本设计不推翻其风险判断本身，而是修订其适用前提：该决策成立依赖「未决条目不会滞留出保留窗」，而 2026-11-16 起人工接受闸门连续约 10 天零消费，前提已失效——2026-11-25 两拍清理删除 4 条 pending（含 7 个回顾窗重复建议放行的种子 6033534dfc34）。SPEC 文档须明示这一定性，避免被理解为修复实现疏漏。

## 方案选型：有界配额，而非无条件豁免

- 无条件豁免（todo 建议①的变体 a）：pending 全部不删。否决——人工永不消费时 pending 只进不出，队列无限膨胀，违背保留清理的截断安全属性，且与「清理面最终一致」的既有语义冲突。
- 龄期上限（变体 b）：pending 超 N 天才删。否决——需再引入一个天数常量，且 N 天内的 pending 在量级爆炸时仍无保护。
- 有界配额（采用）：pending 按 created_at 倒序额外保留前 ITEM_RETENTION_PENDING_MIN 名。覆盖当前 15 条 pending 全量并留余量；超配额最老 pending 仍被淘汰，队列有界；与既有「并集保留集」结构同构，实现最小。

## 实现插入点

- 常量：core/evolution.py 约 149-150 行，与 ITEM_RETENTION_DAYS/ITEM_RETENTION_MIN 同处定义 ITEM_RETENTION_PENDING_MIN = 20（模块常量，与既有两常量口径一致，不新增配置键）。
- 保留集构建：prune_items 内 keep_ids 并集构建处（约 2810 行 ordered[:ITEM_RETENTION_MIN] 之后）追加 pending 配额集——过滤 status=='pending' 的条目按 created_at 倒序取前 ITEM_RETENTION_PENDING_MIN 名并入 keep_ids。
- 清理留痕：统计 victims 中 status=='pending' 的条数，日志行（「自进化条目保留清理：total X，kept Y，deleted Z」）追加「pending W」段。
- victims 差集逻辑（约 2818 行）不变——配额集并入 keep_ids 后差集自然排除配额内 pending。

## 与人工面的边界

本 SPEC 只防「待裁决资产无声蒸发」，不解决「队列为何积压」：根治是人工批量裁决（dashboard 设置页自进化页签）或用户打开 self_evolution.auto_accept（core/config.py:131 缺省 false）。SPEC 归档后仍需人工动作消费队列；被删的 4 条种子由后续分析 run 依现行 todo 条目重新登记（id 为确定性哈希，同内容重放即重入队）。

## 风险

- 配额 20 被长期占满且无消费：日志 deleted_pending 面可暴露该状态，提示人工介入；不引入自动升级机制（超出本 SPEC 范围）。
- pending 状态被滥用为免清理通道：worth_spec 条目登记时 status 即 pending、由框架流转，非用户可随意标注，滥用面可控。