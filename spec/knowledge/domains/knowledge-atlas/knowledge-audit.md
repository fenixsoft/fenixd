# 周期 audit 体检与淘汰纠错

<!-- knowledge: capability=knowledge-audit rev=3
     sources=spec/archive/2026-10-05-add-knowledge-atlas-maintenance,spec/archive/2026-10-06-evo-add-knowledge-audit-finding-ledger,spec/archive/2026-10-07-evo-add-knowledge-audit-escalation-consumption -->

对知识真相源做每日全量体检的维护车道：检测病灶、分级处置，疑点判定跨日记忆，超龄疑点转人工仲裁闭环，防真相源腐烂与膨胀。

## 规则

- 调度：每日一次、自然日语义（对齐自省调度先例），挂 daemon 主循环自然日检查点（与自动归档同款周期检查模式）。`knowledge.audit_enabled`（布尔，缺省 true）为 false 时当日不派发，无告警与日志噪音；配置改动经既有 30s 热更新生效。设置页「归档」页签的 knowledge 设置卡片承载该开关。
- 体检范围——五类病灶：①同页或跨页规则矛盾（同一事实两处陈述不一致）；②溯源链接悬空（指向不存在的归档目录）；③跨页重复规则（同一规则在多个能力页重复陈述）；④超 150 行硬顶页；⑤ADR 病灶（supersede 链断裂、accepted 正文被改动、index 状态与条目头不一致）。
- ADR 引用断链按前缀匹配：检查知识页 ADR 引用时按 `ADR-\d{3}` 前缀匹配盘上 slug 形态文件名（如 `ADR-015-<slug>.md`），存在对应 slug 文件的引用不得判断链——精确名比对会对 slug 形态文件永久误报。
- 分级处置，两级各司其职：
  - 机械项（悬空溯源行删除、格式违规、行数硬顶超标报告）由确定性脚本自动修复并 pathspec 限定 `spec/knowledge/` 提交，commit 形如 `[fenix] knowledge: audit fix <摘要>`。
  - 语义项（矛盾、重复）禁止脚本直接改写：转定向蒸馏 run，给两处冲突上下文、按增量蒸馏契约重写受影响页；成功后自动提交计入「转写」，重写失败登记 todo.md 计入「待人工」。
- 疑点台账：每个语义疑点持久化到 `.fenix/knowledge_audit_findings.json`（原子写），指纹为键——指纹 = sha256(kind + 两页相对路径 + 归一化规则行)，跨文本噪声稳定、不依赖 run 输出文本；条目记录 kind、页对、规则行、两页全文 sha256（缺页按空串哈希）、判定历史（verdicts：日期/判定/提交）与状态。台账缺失或损坏按空台账 fail-open，不炸初筛。
- 疑点状态机：`suspected → exempt`（no-conflict 且记录两页哈希）｜`fixed`（重写提交落账）｜`superseded-in-batch`（同批快照滞后跳过）｜`escalated`（终态，人工仲裁消费后清除）；任一页内容哈希变化时 exempt 解冻回 `suspected`。
- no-conflict 按内容豁免：同指纹上一次判定为 no-conflict 且两页全文 sha256 均未变时，跳过派发复核 run、计入 exempt 统计并记录豁免发生时间。豁免键必须是内容哈希而非仅规则行指纹——同规则行在不同内容语境下判决会翻转，只有内容未变才允许免复核；任一页内容变更即自动解冻、回 suspected 照常派发，保住「复核结论会翻转」情形的再审价值。
- 待人工挂起：登记待人工的疑点停止自动重派复核，挂起等人工消费；同批内规则行来自扫描开始时快照、且涉及页在本批已被纠偏（转写提交或机械自修提交）的后续疑点标 `superseded-in-batch` 跳过。
- 二轮升级：同一指纹连续两轮进入复核且两轮均未产出确定性判定（状态仍 suspected，如转写失败回滚）时，置 `escalated` 终态并停止自动复核；豁免解冻触发的重派不计入升级轮次（每次内容变更重置）。
- escalated 不占转写预算：语义转写候选在按 `MAX_SEMANTIC_RUNS`（10）切片之前，先按台账 escalated 指纹整批剔除——escalated 积压不占用转写名额，新候选每日照常入账；escalated 的报告留痕在循环外统一渲染，不进转写循环。
- 升级聚合与唯一人工入口：体检报告把 escalated 明细折叠为单条汇总节（条数 + 自 first_seen 起算的最长龄期），不再逐条展开；todo.md 升级登记收敛为单条聚合行（前缀「audit 疑点升级待人工（聚合）」，内容 = N 条待仲裁 + 最长龄期 + 仲裁清单路径），按前缀 upsert 整行替换——龄期推进时替换而非追加，聚合行不成为每日重述；escalated 清零后聚合行与报告汇总节随之摘除。
- 人工仲裁清单：`.fenix/knowledge_audit_arbitration.json` 是 escalated 疑点的唯一人工仲裁入口，条目含 fingerprint、decision（`fixed`｜`no-conflict`｜`false-positive`）、decided_at、note（目录整体 gitignore，人工本地裁决不入库）。框架在 knowledge_daily_check 挂独立仲裁消费段——位于 audit_enabled 门控之后、自然日防重短路之前，随 300s 检查点执行，当日体检已跑仍当日消费，不推迟至次日。命中台账 escalated 指纹且 decision 合法即 `_record_verdict` 落判定并删除台账条目，同轮摘除涉事页注记并自提交；删除后台账条目缺席自然恢复该页对的自动复核（既有条目重建语义）。未知指纹、非 escalated 状态或非法 decision 跳过并留痕，不抛错不阻断审计；清单缺失或为空时零写零提交（不创建文件、台账逐字节不变），消费段保持检查点轻量。
- 初筛宁松勿紧：脚本初筛只做召回，误报进 run 由 LLM 终判，可直接判「无矛盾」零改动收场；漏报由下一轮体检补上。
- 体检报告：落 `.fenix/knowledge_audit_report.md`（运行时），含过/修/转写/待人工四计数与明细，另有 exempt（内容未变豁免跳过）、superseded（同批快照滞后跳过）档计数；escalated 有积压时另出「升级待人工（escalated）汇总」单节（代替明细展开）；真相源无病灶时产出「通过」报告、不产生修复提交。
- 状态检查点合并回写：每日检查点写回 `knowledge_audit_state.json` 前必须重读盘上状态并合并，`run_audit` 内部键（如 `last_scale`）的写入不得被陈旧副本覆盖；规模趋势（页数/行数相对上次体检的变化，增长超 +10% 时显式标记「需精简」并给出按行数排序的候选页清单，供下一轮蒸馏/audit 处置）依赖该合并才能跨日可见。
- 配置键（`knowledge` 节，config.template 已登记）：`no_conflict_exempt`（布尔，缺省 true）置 false 关闭内容豁免；`escalate_after_rounds`（正整数，缺省 2）为二轮升级阈值；`escalated_stale_days`（正整数，缺省 7）为超龄注记阈值。三键均须在 get_knowledge_lane_config 白名单登记（未登记键不透传），非法值回退缺省并容错，不炸车道。配置经 knowledge_daily_check 挂载点向车道透传，改动走既有热更新。

## 溯源

- 2026-10-05 add-knowledge-atlas-maintenance（spec/archive/2026-10-05-add-knowledge-atlas-maintenance） — 新增本能力页：五类病灶检测、机械自修/语义转写两级处置、初筛宁松勿紧、体检报告四计数、规模趋势「需精简」标记
- 2026-10-06 evo-add-knowledge-audit-finding-ledger（spec/archive/2026-10-06-evo-add-knowledge-audit-finding-ledger） — 新增疑点台账（指纹持久化、判定回写、五态状态机、fail-open）、no-conflict 内容豁免与内容变更解冻、待人工挂起与同批快照滞后去重、二轮升级 todo.md 登记、ADR 断链前缀匹配（消除精确名永久误报）、state 检查点合并回写（救活 last_scale 规模趋势）、no_conflict_exempt 与 escalate_after_rounds 配置键
- 2026-10-07 evo-add-knowledge-audit-escalation-consumption（spec/archive/2026-10-07-evo-add-knowledge-audit-escalation-consumption） — 修订本能力页：escalated 不再占用语义转写预算（切片前剔除，解除积压冻结）、报告与 todo 收敛为单条聚合（聚合行同前缀 upsert）、超龄 disputed 注记（三红线+写入/摘除自提交）、仲裁清单当日消费闭环（独立消费段避开防重短路、合法 decision 落判定删条目恢复复核）、escalated_stale_days 配置键
