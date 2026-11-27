# 设计：知识体检待人工项降噪与消费接线

## 关键决策

- D1 目录放行收窄在判定分支：仅在 token 为目录级引用形态且 (proot/path).is_dir() 为真时放行；文件 token 判定与行号违例判定不变——避免把「引用了不存在的目录」漏报。与 validate_knowledge 的 sources is_dir 放行口径对齐（core/knowledge.py:647）；锚点判定行为 core/knowledge.py:889。
- D2 登记走 todo 替换语义而非 findings 台账：两类待人工发现以独立前缀 upsert 进 .fenix/todo.md（复用 core/knowledge_backfill.py upsert_todo_line 既有机制）。登记粒度取**逐页一行**（非逐发现一行）：行前缀指纹 = 固定段 + 页面 rel，行内逐发现列明路径；页内发现清零即按 upsert 空行纯清理语义摘除整行，发现集变化按 upsert 整行替换收敛。依据：upsert_todo_line 行粒度为「同前缀收敛为单条、多条历史行一并清理」（core/knowledge_backfill.py:272-335），逐发现一行须逐条独立前缀、绕开该机制；且 escalated 通道曾用逐条行后收敛为单聚合行并清理历史逐条行（core/knowledge_audit.py:110-113 TODO_ESCALATED_LEGACY_PREFIX 清理先例），逐条行形态已被本仓实践否决——当前 33 条非目录类悬空（跨仓引用/概念词形，见非目标）无法自动自愈，逐条行会把 todo.md 永久污染为 33+ 行，逐页聚合把上界压到 ≤10 行（当前涉事页数）。新前缀 MUST NOT 与 TODO_ESCALATED_AGG_PREFIX / TODO_ESCALATED_LEGACY_PREFIX 构成前缀关系，防 cleanup_prefixes 误清 escalated 聚合行。刻意不写 knowledge_audit_findings.json 台账，避免与在途草稿 evo-add-knowledge-audit-reminder-downfreq 的 escalated 提醒降频面发生台账结构交叠。
- D3 标签收敛：报告病灶⑥节标题与明细档位去掉「定向转写」或注明仅待人工，消除无通路措辞。

## 风险与对策

- 风险：目录放行放过「页面想引用某文件却写成目录」的笔误——对策：仅放行实存目录；检查器定位是提示而非硬门（归档件 D2 已定语义），误报代价高于漏报代价，取宁可放过。
- 风险：todo 登记行与人工手写行冲突——对策：独立前缀 + upsert 替换语义与既有体检聚合行一致，不触碰其他行；摘除仅限本前缀行。
- 风险：33 条非目录类悬空（跨仓引用约 25 条、概念词形约 8 条，评审探针 2026-11-27 实测）登记后永不触发自动摘除——对策：逐页聚合限行数上界；非目标已声明不为两类误报加豁免机制，驻留至人工处置属可见可裁决状态（较「发现即终点」的无声重报更可消费）。upsert 幂等短路（同前缀单行且内容未变零写盘不提交）保证发现集未变时 todo.md 零提交噪声。