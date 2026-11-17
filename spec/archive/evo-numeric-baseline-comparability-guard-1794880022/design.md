# Design: numeric-baseline-comparability-guard

## Context

验证链跨轮比较的现状：verdict_stability（core/verify_report.py）只存 status+failed_ids，证据包组装在 core/adjudication_narrative.py，arbiter 判定提示词在 agents/arbiter.md。2026-11-08 client-ux 1080p 争议链中，采集几何 cb0536b 后从 1920x1080 变为 1072x2400，跨轮 fps 直接比较失真且框架全链路无一处可见。

## Goals / Non-Goals

- Goals：不可比基线在快照、证据包、仲裁提示词三层显形；比较结论强制声明可比性。
- Non-Goals：不实现 progress 几何字段的采集（产品侧 run_matrix.py 配套，元数据缺失时守卫按「不可比」保守处理）；不改变验证执行与判定流程语义。

## Design

1. **指纹（core/verify_report.py）**：写 verdict_stability stamp 时从当轮 progress 提取摘要指纹（组合条数 + 每组合可用的几何/管道字段拼接哈希；字段缺失记 None）。相邻轮比对在现有稳定性比较处执行，指纹不一致 → 报告与 stamp 增加 baseline_comparable=false 标注。读取侧对缺字段旧数据按未知处理。
2. **证据包（core/adjudication_narrative.py）**：组装证据包时若引用跨轮数值，附「基线元数据 + 可比性结论」段；元数据缺失或指纹不一致时输出「不可比」标注。对下游消费者纯增量。
3. **提示词（agents/arbiter.md）**：判定规范新增一条——跨轮数值基线比较前先核对几何/管道元数据可比性，不可比或缺失时标注不可比、结论降级为待查，不得据此定性回归/豁免。
4. **与产品侧配套的衔接**：progress JSON 几何字段由产品侧脚本增记（本 SPEC 之外）；框架守卫对「字段存在」与「字段缺失」都正确工作（缺失即保守判不可比），因此产品侧落地前后框架侧均有效。

## Risks / Trade-offs

- 元数据缺失时一律标不可比可能偏保守（历史上确有可比轮次无元数据）——取舍为宁可降级不误判，与 env 证据门同一方向。
- 指纹哈希对 progress 结构变敏感，产品侧结构调整会触发「不可比」——属预期行为（结构变更即不可比），报告中呈现明细供人工复核。

## Migration

verdict_stability 新字段向后兼容；证据包为纯增量；提示词即时生效。无数据迁移。