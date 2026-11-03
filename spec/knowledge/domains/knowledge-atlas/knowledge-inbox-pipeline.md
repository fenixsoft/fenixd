# 知识候选区回填管道（_inbox 投递与折叠）

<!-- knowledge: capability=knowledge-inbox-pipeline rev=1
     sources=spec/changes/add-knowledge-inbox-pipeline -->

`spec/knowledge/_inbox/` 候选区是交互会话产出结论的仓内回流入口：自由格式投递，distill 车道折叠收敛进能力页；编年账与积压提醒保证折叠过程可回溯、积压可见。

## 规则

- **候选区与扫描豁免**：`spec/knowledge/_inbox/` 收交互会话（Claude Code / dsh / daemon 车道）投递的候选知识 markdown，自由格式——能力页契约（marker / 150 行硬顶 / 溯源段）对候选条目一律不适用，只求讲清楚（建议背景/结论/证据三段，结论写当前事实而非变更叙述）。`validate_knowledge` 与 knowledge_audit 的扫描范围显式排除 `_inbox/**`（测试钉死豁免，防扫描范围变更误伤）；audit 对候选条目仅按积压提醒计数，不报契约违规。目录含 `README.md` 说明投递契约与折叠语义。
- **piggyback 折叠**：distill 车道每轮在蒸馏当轮 SPEC 之前先消化 `_inbox/` 存量——按条目顺序折叠进相关能力页（或新建能力页），超 150 行硬顶拆主从分片互链，不放行超顶文件；每条独立提交、可中断。折叠落盘前跑实时 `validate_knowledge`，未通过则该条不落盘、条目滞留 `_inbox/` 原地待下轮重试，`log.md` 记失败行；折叠成功后条目移入 `_inbox/done/` 永久保留，折叠到的能力页 marker `sources` 追加 `spec/knowledge/_inbox/done/<条目文件名>`。
- **无独立派发形态**：`_inbox` 非空不构成独立派发条件，无 fold-only 轮形态（ADR-320）；安静周积压滞留是设计内行为，可见性由积压提醒兜底。
- **marker sources 契约**：sources 机器校验在 `spec/changes/<SPEC名>` 与 `spec/archive/<date-名>` 目录形态之外放行 `spec/knowledge/_inbox/done/` 前缀，按 file 形态校验文件真实存在，文件被删即校验失败；其余前缀校验行为不变。`done/` 是溯源永久保留区，禁删改，候选原文永久可考。
- **编年账**：`spec/knowledge/log.md` 为追加式编年账，行前缀 `## [YYYY-MM-DD HH:MM UTC+8] <操作> | <主题>`（操作 ∈ distill/fold/backfill/lint），时间随真相源人类可读惯例走本地时区显式标注（运行时链路仍全链 UTC）；distill/audit/backfill 轮收尾由 daemon 代码侧追加对应行（有折叠时 fold 行先于 distill 行），并发追加不丢行（文件锁/单写者纪律）；历史行禁删改，unix 工具可按日期前缀 grep。
- **归档改写豁免**：`rewrite_source_links_to_archive` 显式排除 `log.md` 与 `_inbox/**`（含 `done/`）——候选原文与编年账逐字节冻结，接受原文中指向已归档 `spec/changes/<名>` 的历史形态文本（静默改写才是违背「永久可考」承诺）；能力页与 ADR 照常改写。
- **积压提醒**：audit 周期轮检测 `_inbox/` 积压，阈值＝积压 ≥10 条或最老条目滞留 ≥7 天（条目 mtime 起算）；触发落 `log.md` lint 提醒行（同轮幂等去重）并更新 dashboard KnowledgeTab 积压计数（含最老条目滞留天数）；不走 AdminStore 人工告警（人工告警降噪偏好）。
- **知识车道 prompt 归位**：四个知识车道 prompt 为 `agents/knowledge-{distill,audit,backfill,prehistoric}.md` 平铺（distill prompt 含折叠管线段），加载点从 `agents/` 加载；`core/knowledge_prompts/` 目录不存在、全仓无旧路径残留引用——`agents/` 是 prompt 唯一真相，知识车道不破例。prompt 路径变更须 daemon 重启生效（restart_request 交付项）。

## 关键行为

- 候选条目闭环：交互会话投递 → 下一轮 distill 折叠（能力页规则段出现折叠内容、sources 含 `done/` 路径、机器校验通过）→ 条目移 `done/` → `log.md` 依次追加 fold 行与 distill 行。
- `_inbox` 有积压但无任何待蒸 SPEC 批次时不派发任何 run；积压由 lint 提醒行与 KnowledgeTab 计数兜底可见。

## 溯源

- 2026-11-03 add-knowledge-inbox-pipeline（spec/changes/add-knowledge-inbox-pipeline/） — 新增本能力页：_inbox 候选区投递契约与扫描豁免、piggyback 折叠管线、marker sources 扩展（done/ file 形态）、log.md 编年账、归档改写豁免、积压提醒（log 行+面板计数、不走人工告警）、知识车道 prompt 归位 agents/
