# 验证报告：add-knowledge-inbox-pipeline

> ⚠️ 本报告由框架于 2026-11-03T10:56:34Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-03T10:46:11.048033+00:00+run-result@mtime1793703380740634262

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 8/13 场景通过，2 失败，0 错误（1 个真实产品 Bug）**

13 场景：8 pass、2 fail、3 blocked-env 级联。fail 归因：cli-prompts-migrated-agents=product-bug（restart_request 虚假交付，major）；api-knowledge-index-inbox-baseline=test-defect 场景文件缺陷（缺前置自净，已原地修复 preclean）并级联阻塞 seed/count/web 三场景。修复后重执行基线链应全绿；restart_request 缺口走 bug-found 派 implementer 补交付（写根路径 JSON reason/origin/date 且 origin=spec/changes/add-knowledge-inbox-pipeline 并提交）。

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 2 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 7.22M |
| 本链增量 Token（输出） | 0.17M |


## 真实产品 Bug

### BUG-01（severity=major）· output_match

- 关联场景：cli-prompts-migrated-agents
- 描述：tasks 7.2 声称落位的 restart_request 交付物缺失（虚假交付）：根路径 restart_request 自 2026-11-01 13:27 起未被写入，内容仍为上一 SPEC（add-arbiter-quality-display）的重启请求；全仓库历史提交（git log --all -S）零次包含 origin 关联 add-knowledge-inbox-pipeline 的该文件，而提交 950f0d777 信息与 tasks.md 7.2 均声称已交付。知识 prompt 迁移 agents/ 后常驻 daemon 未收到重启信号
- 根因：implementer 7.2 收尾时未实际写入（也未提交）本 SPEC 的 restart_request：文件 mtime 停留在 2026-11-01 13:27（arbiter 交付时刻），提交 950f0d777 信息含「+ restart_request」但该提交未触碰该文件
- 证据（场景 cli-prompts-migrated-agents 结构化证据，引用）：
  - failed_assertions: [{"type": "output_match", "selector": "restart 步骤 output_match", "expected": "RESTART_OK", "actual": "RESTART_BAD"}]
  - screenshots: []
  - first_failed_step: 步骤5（as=restart）: restart_request JSON 可解析但 origin=spec/changes/add-arbiter-quality-display 不关联本 SPEC；stat mtime=2026-11-01 13:27:16 证明本 SPEC 工作窗（11-03 提交 950f0d777）从未写入该文件


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
| api-knowledge-index-inbox-baseline | 积压计数空态基线（回归点·播种前）：GET /api/knowledge/index?project=fenixd 返回 200、initialized=true、inbox_backlog.count=0（_inbox 仅有 README.md 不计条目、done/ 恒不计）。字段名 inbox_backlog.count/oldest_stay_days 为实现单源契约（core.knowledge.inbox_backlog → knowledge_routes.py:169-186 装配，组件 KnowledgeTab.tsx:459-469 同源消费）；本场景修正自臆测字段名 inbox.pending。端点出处：core/dashboard/routes/base.py:732（路由注册）→ core/dashboard/routes/knowledge_routes.py:143（_api_knowledge_index 处理器） | failed（已修正） | 1/3 | test-defect |
| cli-prompts-migrated-agents | 知识车道 prompt 归位 agents/：四个 agents/knowledge-{distill,audit,backfill,prehistoric}.md 就位、core/knowledge_prompts/ 目录不存在、活代码与活文档（git 跟踪面：core/ tests/ agents/ core/dashboard/static/src/ docs/）grep knowledge_prompts 残留引用为 0（2026-11-03 裁决原地修复：未跟踪并发设计文档不入验收面）、加载点实读新路径成功（distill loader 返回非空且含 _inbox 折叠段、audit/backfill/prehistoric PROMPT_PATH 常量指向存在的 agents/ 文件）、restart_request 交付物落位（根路径 JSON 含 reason/origin/date 且 origin 关联本 SPEC）（tasks.md 7.1/7.2、spec.md「新路径加载成功且旧路径消失」） | failed（已修正） | 1/13 | product-bug |
| cli-seed-inbox-backlog-fixture | 注入积压夹具（供 dashboard 计数场景确定性驱动）：_inbox/ 下播种 3 条待折叠候选（zn-inbox-entry-1/2/3.md，entry-1 mtime 经 touch -d 回拨 20 天作最老滞留条目）+ 1 条置于 _inbox/done/（不得计入积压，鉴别点）。种子的是夹具候选而非被测端点——/api/knowledge/* 打真实实例。夹具 token：zn-inbox-token-N。zn-* 残留幂等清除 | failed（已修正） | - | test-defect |
| cli-validate-tree-clean | 回归点·全树校验无回归：清场历史探针残留（zn-bad-*）后对验证树跑 validate_knowledge 零违规——marker sources 契约扩展与 _inbox 豁免改动不破坏既有 851 文件的校验通过态（SPEC A 同款基线断言） | pass | 0/2 | - |
| api-knowledge-index-inbox-count | 积压计数播种后生效（dashboard 数据源）：GET /api/knowledge/index?project=fenixd 返回 inbox_backlog.count=3（README.md 与 done/ 条目均不计入——计数=3 而非 4/5 即为鉴别断言）、inbox_backlog.oldest_stay_days 命中 20-21 天窗（最老条目 mtime 回拨 20 天，容许 floor/trunc 计算差 ±1）。字段名 inbox_backlog.count/oldest_stay_days 为实现单源契约（同 baseline）；本场景修正自臆测字段名。端点出处：core/dashboard/routes/base.py:732 → core/dashboard/routes/knowledge_routes.py:143 | failed（已修正） | - | test-defect |
| web-knowledge-inbox-backlog-visible | KnowledgeTab 积压计数可见：fenixd 项目页点选「项目知识」页签（按需加载门控真实驱动），知识总目录渲染且 [data-testid=knowledge-inbox-backlog] 积压徽标可见——计数含 3、滞留文案含「天」（最老条目滞留天数展示）。徽标为纯展示元素（declared_display 登记）。data-testid=knowledge-inbox-backlog 为本场景钉死的展示契约。出处：SPA 路由 /projects/:name（core/dashboard/static/config/routes.ts:51）、hash 路由（core/dashboard/static/config/config.ts:15）、页签 key=knowledge（core/dashboard/static/src/pages/projects/list.tsx:1741-1746）、KnowledgeTab 总目录视图（core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx:449-468） | failed（已修正） | - | test-defect |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| api-knowledge-index-inbox-baseline | json_path inbox_backlog.count == 0（播种前空态基线，layer 3） | test-defect | 测试用例自身缺陷（非产品缺陷） | 同响应 status_code/initialized 已过；count=3 与空态基线矛盾，_inbox 残留上轮种子夹具 zn-inbox-entry-1/2/3.md（token 与 mtime 回拨 20 天指纹吻合）。场景文件缺陷已修复：基线 steps 前插入幂等 preclean（仅清 zn-* 夹... |
| cli-seed-inbox-backlog-fixture | 依赖 api-knowledge-index-inbox-baseline 通过（依赖序前置门） | test-defect | 测试用例自身缺陷（非产品缺陷） | error 原文「依赖场景失败，未执行: api-knowledge-index-inbox-baseline（依赖失败传播，非本场景产品缺陷）」；本场景无自有断言获执行机会，级联根因=链顶场景缺前置自净 |
| api-knowledge-index-inbox-count | 依赖 cli-seed-inbox-backlog-fixture 通过（依赖序前置门） | test-defect | 测试用例自身缺陷（非产品缺陷） | error 原文「依赖场景失败，未执行: cli-seed-inbox-backlog-fixture（依赖失败传播，非本场景产品缺陷）」；级联根因=链顶 api-knowledge-index-inbox-baseline 缺前置自净，本场景计数断言未获执行机会 |
| web-knowledge-inbox-backlog-visible | 依赖 cli-seed-inbox-backlog-fixture 通过（依赖序前置门） | test-defect | 测试用例自身缺陷（非产品缺陷） | error 原文「依赖场景失败，未执行: cli-seed-inbox-backlog-fixture（依赖失败传播，非本场景产品缺陷）」；级联根因=链顶 api-knowledge-index-inbox-baseline 缺前置自净，UI 徽标断言未获执行机会 |

## 本轮场景集变更

场景集与持久化集一致，无变更。

