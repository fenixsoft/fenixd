# 验证报告：add-knowledge-anchor-lint-and-prune

> ⚠️ 本报告由框架于 2026-11-07T17:06:01Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-07T17:05:59.948005+00:00+run-result@mtime1794071159999829785

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.10M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| anchor-check-clean-tree-zero | 全树锚点存活零报告：对验证树真实 spec/knowledge 跑 check_anchor_references 与 validate_knowledge 双零（范例锚点页即自证），且三个高频消费范例页（unified-page-title-bar/spec-doc-view/activities-page）均含「## 代码锚点」段（spec/changes/add-knowledge-anchor-lint-and-prune 4.1-4.2） | pass | 0/6 | - |
| anchor-scope-semantics | 锚点检查扫描面语义：临时知识树夹具验证——段内悬空路径报「锚点悬空」、规则段/溯源段路径不扫、spec/archive 与 _inbox 与 node_modules 前缀豁免、_domain.md 域导航页不在扫描面、路径:行号形态报「行号必腐」格式违规（core/knowledge.py check_anchor_references） | pass | 0/7 | - |
| anchor-not-in-fold-hard-gate | 锚点检查不并入折叠硬门（design D2）：同夹具树上存在悬空锚点时 validate_knowledge 仍零违规——一处陈旧锚点不得阻塞全树折叠校验 | pass | 0/4 | - |
| adr-retired-validation-matrix | ADR retired 词汇校验矩阵：retired+日期注记行合规放行；缺 Retired: 注记行报违规；注记行无 YYYY-MM-DD 日期锚报违规；accepted 无注记行照旧零违规；合法 superseded 照旧放行、缺 Superseded by 行照旧报违规——既有二值行为零回归（core/knowledge.py _ADR_STATUS_RE/_RETIRED_NOTE_RE） | pass | 0/7 | - |
| adr-retired-immutability-git | retired 三段正文不可变比对与 superseded 同口径：git 夹具 ADR 提交后，头部补 Retired: 注记行不触发改写违规；改写三段正文报「三段正文被改写」（tests/test_knowledge_anchor_check.py 场景 5 同款） | pass | 0/3 | - |
| audit-lesion-six-pending-manual | 体检病灶⑥接线：临时知识树夹具（悬空锚点页）直接跑 run_audit——悬空计入 counts.pending_manual、体检报告落「病灶⑥」独立节并列明「锚点悬空: core/demo.py」、悬空锚点行不被机械自删（core/knowledge_audit.py 消费 check_anchor_references） | pass | 0/6 | - |
| retirement-content-pruned-state | 存量清理落盘状态：五个 amis 壳退役页已删除、runbook 页在盘、dashboard-platform 域表五行移除且表尾退役注记行在位、域页「症状速查」段在位、index.md 计数 dashboard-platform=20 与 knowledge-atlas=14、adr/index.md 五条 ADR 翻 retired 且 ADR-037 保持 accepted、log.md 登记退役批（spec/changes 3.1-3.4） | pass | 0/12 | - |
| retirement-no-dangling-refs | 退役收口复核 grep：五页 capability 名与五条 ADR 编号在 spec/knowledge+agents+core 扫描面零悬空残留——log.md 编年账、_domain.md 表尾「> 退役：」注记行、adr/ 条目本体、spec/archive 与 _inbox 豁免（历史溯源行的纯文本提及不算残留） | pass | 0/3 | - |
| prompt-contract-anchor-line | 提示词面轻量接线（design D5）：agents/knowledge-distill.md 模板与 core/knowledge.py build_inbox_fold_prompt 内联段各含「新建能力页必带 ## 代码锚点 段（文件级禁行号）」执行提醒一句 | pass | 0/4 | - |
| contract-pages-documented | 契约页文档交付：knowledge-atlas-directory.md 含锚点段四类标签/禁行号契约、退役即删不墓碑语义、世代前缀命名禁令、症状速查段登记；knowledge-audit.md 含病灶⑥检测口径与两道纪律边界（不机械自删、不进 validate_knowledge 硬门）；knowledge-retirement-runbook.md 八步 checklist 关键步骤在位（spec/changes 2.1-2.3） | pass | 0/15 | - |
| anchor-test-suite-green | 新增守卫测试全绿：pytest tests/test_knowledge_anchor_check.py -v 逐用例 PASSED（17 例）与汇总 17 passed（spec/changes 1.3/5.1） | pass | 0/7 | - |
| knowledge-family-regression-green | 既有知识测试族零回归：tests/test_knowledge_*.py 九文件全量 -q 跑批，237 passed 汇总断言（spec/changes 5.1） | pass | 0/2 | - |
| api-knowledge-index-surface | 知识总目录只读端点反映清理后真相源：GET /api/knowledge/index?project=fenixd 返回 200、initialized=true、domains 清单含 knowledge-retirement-runbook.md、五条 retired ADR 状态在 adrs 数组可查且 ADR-037 保持 accepted（端点实现 core/dashboard/routes/knowledge_routes.py:127；无 mock，打真实实例） | pass | 0/10 | - |
| api-knowledge-file-endpoints | 知识单文件只读端点退役语义：GET /api/knowledge/file 取 runbook 页 200 且正文含 checklist；取已删除的 v2-shell-router.md 404 文件不存在（白名单内缺失语义，core/dashboard/routes/knowledge_routes.py:267） | pass | 0/4 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

