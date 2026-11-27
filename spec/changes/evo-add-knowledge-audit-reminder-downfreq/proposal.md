# 提案：知识体检聚合提醒龄期降频

## 背景与问题

知识真相源体检（core/knowledge_audit.py）对人工仲裁欠账的聚合提醒是每日一拍：run_audit 收尾把「N 条待人工仲裁（最长龄期 X 天）」聚合行 upsert 进 todo.md 并走既有自动提交路径（core/knowledge_backfill.py upsert_todo_line → _commit_todo_after_write）。聚合行内嵌龄期逐日 +1，使 upsert 的「行内容逐字节相同即幂等短路」必然失效——同前缀聚合提醒提交已累计 37 次（2026-10-15 起，git log 计数），且条目数还在增长（10→11→13），无自然停止点。

根因不是体检漏报（体检与消费机制按设计工作），而是提醒面无龄期衰减：机制原始 SPEC（归档 2026-10-07-evo-add-knowledge-audit-escalation-consumption）设计即无降频，upsert 调用点（core/knowledge_audit.py:2246-2251）无任何龄期条件分支。人工 52 天未登记仲裁属人工闭环欠账（另行推进），但机制性每日提交噪音应由框架自愈。

## 目标

1. 同一条目集的 escalated 聚合提醒降频为每周一拍：距上次提醒不足 7 天且 escalated 指纹集未变化时跳过 upsert（不写盘不提交），log 留痕。
2. 条目集变化（新增或减少 escalated 疑点）旁路降频立即拍——新疑点升级不被掩盖；upsert 整行替换语义天然保证新集内容完整写入。
3. escalated 清零（仲裁消费/人工删条目）时保持现有纯清理语义照常摘除残留行，不受降频抑制。
4. 提醒行尾附下次提醒日期，缓解降频期间 todo 行龄期文案停留旧值的误导。

## 非目标

- 不改仲裁消费侧 consume_arbitration（挂 300s 检查点、人工登记当日生效语义保持）。
- 不改 findings 台账结构、体检扫描逻辑与 disputed 注记机制。
- 不自动处置台账条目（催办与人工闸门分工维持现状）。