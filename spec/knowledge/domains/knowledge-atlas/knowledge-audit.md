# 周期 audit 体检与淘汰纠错

<!-- knowledge: capability=knowledge-audit rev=1
     sources=spec/archive/2026-10-05-add-knowledge-atlas-maintenance -->

对知识真相源做每日全量体检的维护车道：检测病灶、分级处置，防真相源腐烂与膨胀。

## 规则

- 调度：每日一次、自然日语义（对齐自省调度先例），挂 daemon 主循环自然日检查点（与自动归档同款周期检查模式）。`knowledge.audit_enabled`（布尔，缺省 true）为 false 时当日不派发，无告警与日志噪音；配置改动经既有 30s 热更新生效。设置页「归档」页签的 knowledge 设置卡片承载该开关。
- 体检范围——五类病灶：①同页或跨页规则矛盾（同一事实两处陈述不一致）；②溯源链接悬空（指向不存在的归档目录）；③跨页重复规则（同一规则在多个能力页重复陈述）；④超 150 行硬顶页；⑤ADR 病灶（supersede 链断裂、accepted 正文被改动、index 状态与条目头不一致）。
- 分级处置，两级各司其职：
  - 机械项（悬空溯源行删除、格式违规、行数硬顶超标报告）由确定性脚本自动修复并 pathspec 限定 `spec/knowledge/` 提交，commit 形如 `[fenix] knowledge: audit fix <摘要>`。
  - 语义项（矛盾、重复）禁止脚本直接改写：转定向蒸馏 run，给两处冲突上下文、按增量蒸馏契约重写受影响页；成功后自动提交计入「转写」，重写失败登记 todo.md 计入「待人工」。
- 初筛宁松勿紧：脚本初筛只做召回，误报进 run 由 LLM 终判，可直接判「无矛盾」零改动收场；漏报由下一轮体检补上。
- 体检报告：落 `.fenix/knowledge_audit_report.md`（运行时），含过/修/转写/待人工四计数与明细；真相源无病灶时产出「通过」报告、不产生修复提交。
- 不膨胀维护目标：报告含真相源规模趋势（页数/行数相对上次体检的变化），增长超阈值（+10%）时显式标记「需精简」并给出候选页清单（按行数排序），供下一轮蒸馏/audit 处置。

## 溯源

- 2026-10-05 add-knowledge-atlas-maintenance（spec/archive/2026-10-05-add-knowledge-atlas-maintenance） — 新增本能力页：五类病灶检测、机械自修/语义转写两级处置、初筛宁松勿紧、体检报告四计数、规模趋势「需精简」标记
