# 验证报告：add-knowledge-inbox-pipeline

> ⚠️ 本报告由框架于 2026-11-03T14:55:38Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-03T14:55:37.040924+00:00+run-result@mtime1793717737106429659

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.58M |
| 本链增量 Token（输出） | 0.20M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-inbox-readme-contract | 候选区地基：spec/knowledge/_inbox/README.md 落位且写明投递契约——自由格式 markdown 不守能力页契约、折叠成功移 _inbox/done/、校验失败滞留原地待下轮重试（tasks.md 1.1） | pass | 0/5 | - |
| cli-validate-inbox-exemption | 烂格式候选不触发契约违规（validate 侧）：_inbox/ 夹具含无 marker、超 150 行、失效链接与 spec/changes 死引用的候选 markdown，validate_knowledge 零 _inbox 违规；同内容临时放入 domains/ 则确定性触发违规（鉴别探针，证明豁免是显式排除而非内容碰巧合法）。夹具用后即清（tasks.md 1.2 validate 侧、spec.md「烂格式候选不触发契约违规」） | pass | 0/3 | - |
| cli-audit-inbox-exemption | 烂格式候选不触发体检病灶（audit 侧）：_inbox/ 夹具经 knowledge_audit 页级扫描（_scan_pages 候选集收集点）零 _inbox 条目进 no_marker/超行数/悬空/格式病灶；同内容临时放入 domains/ 则被检出（鉴别探针）。夹具用后即清（tasks.md 1.2 audit 侧、spec.md「烂格式候选不触发契约违规」） | pass | 0/3 | - |
| cli-fold-pipeline-suite | piggyback 折叠管线行为套件全绿（tests/test_knowledge.py，无真实 LLM 调用）：须覆盖 spec.md 四场景——候选条目折叠闭环（能力页规则段折叠内容、marker sources 含 _inbox/done/ 路径且机器校验通过、条目移 done/、log.md 追加 fold 行）/超 150 行拆页（主从分片互链）/实时 validate_knowledge 失败不落盘条目滞留原地/无 SPEC 批次时不派发（piggyback-only：_inbox 非空不产生独立 run）；并覆盖 log.md 编年账（行前缀 ## [YYYY-MM-DD HH:MM UTC+8] <操作> \| <主题> 本地时区、折叠轮先 fold 行后 distill 行、并发追加不丢行文件锁或单写者纪律、写入主体为 daemon 代码侧轮收尾逻辑）；另覆盖积压提醒阈值（积压 ≥10 条或最老条目滞留 ≥7 天 mtime 起算落 lint 提醒行、同轮幂等去重、不写 AdminStore）。task 8.1 端到端（合成 _inbox 夹具→驱动 distill 轮→断言闭环）已由实现并入 tests/test_knowledge.py 族（TestInboxFoldStage 折叠闭环 4 测试 + TestInboxCandidateArea 5 测试，SPEC 8.1 未钉文件名） | pass | 0/4 | - |
| cli-fold-prompt-section | distill prompt 增补 inbox 折叠段：agents/knowledge-distill.md 含折叠前置段语义锚点——先消化 _inbox/ 存量、成功条目移 done/、失败滞留原地待下轮重试、超顶拆页契约（tasks.md 7.1 折叠段增补、3.1） | pass | 0/6 | - |
| cli-marker-sources-inbox-done | marker sources 契约扩展（done 路径机器校验放行）：临时夹具项目能力页 sources 含 spec/knowledge/_inbox/done/<文件>（file 形态，文件存在）→ validate_knowledge 通过；文件删除 → 校验失败；其余前缀（docs/）仍被拒绝、既有 archive/changes 前缀放行行为不变。全程临时目录、不触验证树（tasks.md 2.1、spec.md「done 路径机器校验放行」） | pass | 0/4 | - |
| cli-rewrite-inbox-log-exempt | 归档改写豁免（逐字节冻结）：临时夹具项目内能力页 marker sources 与正文溯源行含 spec/changes/<名>、_inbox/ 待折叠候选、_inbox/done/ 候选原文、log.md 编年账行均含同串——触发 rewrite_source_links_to_archive 后能力页与普通 kroot 页照常改写到 spec/archive/，而 _inbox/**（含 done/）与 log.md sha256 逐字节不变。全程临时目录（tasks.md 5.1、spec.md「归档迁出逐字节冻结候选原文」） | pass | 0/4 | - |
| cli-inbox-preclean-fixture | 跨轮夹具清场（admin 修订自 judge 2026-11-03 原地修复意图）：清除上一轮种子夹具 zn-* 残留（含 entry-1 被回拨 20 天的 mtime 指纹），为空态基线构造播种前干净态；仅清 zn-* 夹具 token，不触碰真实候选。judge 原修复把该步骤插进 api 类场景属词表违规（api 仅 http_request/sse_connect），admin 修订迁移为前置 cli 场景并经 depends_on 挂链保证先于 baseline 执行。2026-11-03 裁决再修订（场景文件缺陷原地修复）：空态基线上轮被真实候选 chain-arbiter-rulings-default-3.md（运行前 14 分钟投递）打破，暴露「仅清 zn-* token 无法保证空态」前提缺陷——本场景升级为夹具清场+真实候选隔离：zn-* 幂等清除后，_inbox/ 顶层非 README 的 *.md（真实候选）移入 .fenix/verify-quarantine/knowledge-inbox/（mv 保 mtime、同名冲突不覆盖），由链尾 cli-validate-tree-clean（depends_on 挂 web 场景后）回迁原位；断言零弱化、零场景增删 | pass | 0/2 | - |
| cli-prompts-migrated-agents | 知识车道 prompt 归位 agents/：四个 agents/knowledge-{distill,audit,backfill,prehistoric}.md 就位、core/knowledge_prompts/ 目录不存在、活代码与活文档（git 跟踪面：core/ tests/ agents/ core/dashboard/static/src/ docs/）grep knowledge_prompts 残留引用为 0（2026-11-03 裁决原地修复：未跟踪并发设计文档不入验收面）、加载点实读新路径成功（distill loader 返回非空且含 _inbox 折叠段、audit/backfill/prehistoric PROMPT_PATH 常量指向存在的 agents/ 文件）、restart_request 交付物落位（根路径 JSON 含 reason/origin/date 且 origin 关联本 SPEC）（tasks.md 7.1/7.2、spec.md「新路径加载成功且旧路径消失」） | pass | 0/13 | - |
| api-knowledge-index-inbox-baseline | 积压计数空态基线（回归点·播种前）：GET /api/knowledge/index?project=fenixd 返回 200、initialized=true、inbox_backlog.count=0（_inbox 仅有 README.md 不计条目、done/ 恒不计）。字段名 inbox_backlog.count/oldest_stay_days 为实现单源契约（core.knowledge.inbox_backlog → knowledge_routes.py:169-186 装配，组件 KnowledgeTab.tsx:459-469 同源消费）；本场景修正自臆测字段名 inbox.pending。端点出处：core/dashboard/routes/base.py:732（路由注册）→ core/dashboard/routes/knowledge_routes.py:143（_api_knowledge_index 处理器）；2026-11-03 admin 修订：judge 原地修复插入的 api 类 run preclean 步骤属词表违规（api 仅 http_request/sse_connect），preclean 意图保留、迁移为前置 cli 场景 cli-inbox-preclean-fixture（depends_on 挂链），断言未弱化 | pass | 0/3 | - |
| cli-seed-inbox-backlog-fixture | 注入积压夹具（供 dashboard 计数场景确定性驱动）：_inbox/ 下播种 3 条待折叠候选（zn-inbox-entry-1/2/3.md，entry-1 mtime 经 touch -d 回拨 20 天作最老滞留条目）+ 1 条置于 _inbox/done/（不得计入积压，鉴别点）。种子的是夹具候选而非被测端点——/api/knowledge/* 打真实实例。夹具 token：zn-inbox-token-N。zn-* 残留幂等清除 | pass | 0/3 | - |
| api-knowledge-index-inbox-count | 积压计数播种后生效（dashboard 数据源）：GET /api/knowledge/index?project=fenixd 返回 inbox_backlog.count=3（README.md 与 done/ 条目均不计入——计数=3 而非 4/5 即为鉴别断言）、inbox_backlog.oldest_stay_days 命中 20-21 天窗（最老条目 mtime 回拨 20 天，容许 floor/trunc 计算差 ±1）。字段名 inbox_backlog.count/oldest_stay_days 为实现单源契约（同 baseline）；本场景修正自臆测字段名。端点出处：core/dashboard/routes/base.py:732 → core/dashboard/routes/knowledge_routes.py:143 | pass | 0/4 | - |
| web-knowledge-inbox-backlog-visible | KnowledgeTab 积压计数可见：fenixd 项目页点选「项目知识」页签（按需加载门控真实驱动），知识总目录渲染且 [data-testid=knowledge-inbox-backlog] 积压徽标可见——计数含 3、滞留文案含「天」（最老条目滞留天数展示）。徽标为纯展示元素（declared_display 登记）。data-testid=knowledge-inbox-backlog 为本场景钉死的展示契约。出处：SPA 路由 /projects/:name（core/dashboard/static/config/routes.ts:51）、hash 路由（core/dashboard/static/config/config.ts:15）、页签 key=knowledge（core/dashboard/static/src/pages/projects/list.tsx:1741-1746）、KnowledgeTab 总目录视图（core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx:449-468） | pass | 0/6 | - |
| cli-validate-tree-clean | 回归点·全树校验无回归：清场历史探针残留（zn-bad-*）后对验证树跑 validate_knowledge 零违规——marker sources 契约扩展与 _inbox 豁免改动不破坏既有 851 文件的校验通过态（SPEC A 同款基线断言）。2026-11-03 裁决再修订（场景文件缺陷原地修复）：挂 depends_on=web-knowledge-inbox-backlog-visible 作整链链尾，首步回迁隔离区真实候选（RESTORED，同名不覆盖）后再清 zn-bad-* 探针残留并跑全树校验——真实候选验证窗结束后原位归还 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 拦截 planner 超发 1 个未声明新增范围的场景（修复轮不扩容，按 D2 丢弃）：cli-inbox-preclean-fixture

