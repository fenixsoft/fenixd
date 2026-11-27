# 设计：知识体检待人工项降噪与消费接线

## 关键决策

- D1 目录放行收窄在判定分支：仅在 token 为目录级引用形态且 (proot/path).is_dir() 为真时放行；文件 token 判定与行号违例判定不变——避免把「引用了不存在的目录」漏报。与 validate_knowledge 第 597 行的 is_dir 放行口径对齐。
- D2 登记走 todo 替换语义而非 findings 台账：两类待人工发现以独立前缀 upsert 进 .fenix/todo.md（复用 core/knowledge_backfill.py upsert_todo_line 既有机制），逐发现一行、带页面路径指纹；每轮体检按当前发现集整组替换，未再报即摘除——自愈语义对齐 evo-fix-distill-retry-ledger-auto-close 的「假欠账不留行」教训。刻意不写 knowledge_audit_findings.json 台账，避免与在途草稿 5ae00be13f08 的 escalated 提醒降频面发生台账结构交叠。
- D3 标签收敛：报告病灶⑥节标题与明细档位去掉「定向转写」或注明仅待人工，消除无通路措辞。

## 风险与对策

- 风险：目录放行放过「页面想引用某文件却写成目录」的笔误——对策：仅放行实存目录；检查器定位是提示而非硬门（归档件 D2 已定语义），误报代价高于漏报代价，取宁可放过。
- 风险：todo 登记行与人工手写行冲突——对策：独立前缀 + upsert 替换语义与既有体检聚合行一致，不触碰其他行；摘除仅限本前缀行。