# Proposal: numeric-baseline-comparability-guard

## Why

2026-11-08 cloud-phone 项目 `client-ux-and-input-latency` 的 1080p 矩阵争议链中，新旧两轮验收进度被当作同一组合直接比较 fps（55.7/58.4 vs 36.2~37.5，「~37% drop」），而采集管道 cb0536b 已把实际几何从 1920x1080 改为 1072x2400（像素 +24.07%）——两轮基线根本不可比，比较失真险些把真实负载增长整体误判为产品回归，并间接支撑了错误的 env 归因（judge_attribution.json 2026-11-08T20:47:56Z accept），链上烧掉连续 2 轮 warning、两次 arbiter run 与升级自环；几何差异最终靠人工 git 考古才发现，因为任何一环的数据或提示都没有几何信息。

框架侧根因（已回源核实）：

1. 跨轮稳定性快照 verdict_stability（core/verify_report.py）只存 status+failed_ids——相邻轮 progress 几何漂移在框架任何观测面都不可见。
2. 仲裁/裁决证据包（core/adjudication_narrative.py）不携带 progress 元数据指纹，也不提示「跨轮数值基线须核对几何与管道版本可比」。
3. arbiter 提示词（agents/arbiter.md）对跨轮数值比较无可比性核查要求——arbiter 直接拿 55.7 与 36.2 对比得出 ~37% drop。

范围说明：progress JSON 逐条增记 vdW/vdH/encW/encH 等几何字段由产品侧采集脚本（cloud-phone scripts/run_matrix.py）承载，不在本框架 SPEC 交付物范围；本 SPEC 落框架侧「比较时的可比性守卫 + 不可比显形」，产品侧记录作为配套依赖在设计中注明。

## What Changes

- **verdict_stability 指纹（core/verify_report.py）**：跨轮稳定性 stamp 增记 progress 摘要指纹（组合数与可用的几何/管道元数据摘要），相邻轮指纹不一致时在 stamp 与报告中显式标注「基线不可比」。
- **裁决证据包注入（core/adjudication_narrative.py）**：证据包组装时注入跨轮数值基线可比性核查要求与可用元数据，比较结论必须先声明基线可比。
- **仲裁提示词（agents/arbiter.md）**：对跨轮数值基线比较增加「先核对采集/编码几何与管道 commit，不可比时显式标注不可比，不得据此定性回归/豁免」的要求。

## Capabilities

### verify-baseline-comparability

见 specs/verify-baseline-comparability/spec.md。

## Impact

- core/verify_report.py 的 verdict_stability 结构新增字段（向后兼容，旧 stamp 可读）。
- core/adjudication_narrative.py 证据包内容扩充（对既有消费者只增不改）。
- agents/arbiter.md 提示词变更即时生效于新 arbiter run。
- 不改变验证引擎执行语义，只影响比较/裁决层的判断输入。