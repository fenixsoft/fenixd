# 提案：自进化条目保留清理 pending 配额豁免

## 背景与问题

自进化台账（.fenix/evolution/items.jsonl）的周期保留清理（core/evolution.py prune_items）按「最近 7 天 ∪ created_at 倒序前 100 名」保留条目，其余一律删除，且删除循环对 status 零判断——等待人工裁决的 pending 条目同样会被删。

该行为源自归档 SPEC evo-item-retention-doc-tracking（2026-09-19）的显式用户决策「清理一刀切全状态」，其成立前提是未决条目不会滞留出保留窗。2026-11-16 之后人工接受闸门连续约 10 天零消费（11-17 起 evo-* spec 物化提交零命中、11-22 至 11-25 每个分析 run 落地行全部「接受 0」），前提已失效：2026-11-25T18:28:37Z 与 18:53:40Z 两拍清理共删 9 条，其中 4 条 pending 具名确认蒸发（6033534dfc34、deb14643f2be、2b343adf6c0c、4a6939ce81bf，草稿目录一并消失）。其中 6033534dfc34 横跨 7 个回顾窗被重复建议「优先放行」、deb14643f2be 6 窗——每日回顾对同一问题的重述生成新条目，新条目加速把待裁决旧 pending 挤出保留集，形成「提醒越多、种子越保不住」的反向循环。

## 目标

1. pending 条目在保留集判定中获得有界配额保护：status 为 pending 的条目按 created_at 倒序额外保留前 ITEM_RETENTION_PENDING_MIN 名（新常量，缺省 20），超配额的最老 pending 仍按常规策略淘汰，保持队列有界。
2. 清理日志补 pending 维度计数（删除的 pending 条数），使 pending 保全效果可审计。
3. 知识页 self-evolution.md 的保留策略口径同步修订。

## 非目标

1. 不改变人工接受闸门语义，不修改 self_evolution.auto_accept 配置行为（根治积压仍靠人工批量裁决或用户打开 auto_accept，属人工面动作）。
2. 不回滚已删除的 4 条 pending（素材在 todo.md 与 git 历史中，由后续分析 run 依现行条目重新登记）。
3. 不做 dashboard 展示层改动。

## 方案概要

在 prune_items 的保留集构建处（keep_ids 并集）追加 pending 配额集：常量 ITEM_RETENTION_PENDING_MIN=20 与既有两常量同处定义；清理日志行追加 pending 删除计数。配额制而非无条件豁免的理由：无条件豁免在人工永不消费时使 pending 只进不出、队列无限膨胀，违背保留清理的截断安全属性；配额 20 覆盖当前 15 条 pending 全量并留余量，同时保证超龄 pending 最终仍被淘汰。

## 与既有交付的关系

修订 2026-09-19-evo-item-retention-doc-tracking design.md 记录的「一刀切全状态」决策（design.md:8/74），引用其前提失效证据；查重确认 spec/changes/ 与近 30 天归档无 retention/prune 同主题在途。