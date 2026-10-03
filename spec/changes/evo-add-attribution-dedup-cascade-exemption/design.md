# 设计（add-attribution-dedup-cascade-exemption）

## 现状与根因

- 查重门：core/verdict_check.py:1280-1345 _batch_attribution_dedup_common——:1309 排除 pass、:1315 归一化分组、:1321 组阈值 ≥3（写死）、:1323-1332 违规 reason 拼接（与日志文案逐字同源）。
- 归一化指纹：:1204-1240 _normalize_attribution 三段（cls=/step=/a=），依赖跳过场景仅剩 cls= 段——同因组天然同文。
- 证据真空的语义源头：core/verify_engine/engine.py:408-428 依赖失败传播合成 blocked-env（:423 dependency_skipped=True，步骤/断言/截图全空，统一跳过文案 :412-415「依赖场景失败，未执行: …（依赖失败传播，非本场景产品缺陷）」）。
- D3 细分（2026-09-17-fix-verdict-dedup-resynthesis）只覆盖「步骤/断言各异」形态；:1104-1112 注释自认「不设组内豁免分支」，其 verification-report.md:25 把「无步骤无断言同文→仍拒」列为通过用例。
- 实测代价：误拒一次重合成 $0.9174/303s 与 $0.4428/258s（run 档案 planner-judge-android-station-port-1791033836-a1 / 1791049328-a1）。

## 方案决策

1. **豁免锚点用 dependency_skipped 标记而非文本比对**：分组阶段（:1315）把 dependency_skipped=true 的场景从「逐字同文」判据中单列——该标记由引擎结构化写入（engine.py:423），比比对统一文案更稳（文案改动不破坏豁免）。
2. **混合组语义保持**：组内含非 dependency_skipped 的同文场景时，仅对非级联子集计阈值——3 个真实 failed 同文仍满足 ≥3 照拒（本次第一轮形态即被保留拦截），防套用能力零回退。
3. **留痕而非静默**：豁免命中时 reason/日志记「同因级联组豁免（N 场景，dependency_skipped）」，经既有收口链（verdict_evidence.py:113-140）透传，便于事后审计豁免是否被滥用。
4. **弃用缓存标记方案**：核查证实 verdict_cache.json 不含归因文本（schema：status＋三指纹，verdict_check.py:1393-1398），「缓存携带同因组标记」无落点；且被拒文本来自当轮报告自身，与缓存无关。

## 风险

- 豁免被滥用（实现 run 对真实失败场景伪标 dependency_skipped）：该标记由引擎（非 judge）写入，报告侧伪造会被引擎日志依赖跳过链交叉对穿；测试覆盖「judge 报告自declared dependency_skipped 与引擎跳过链不一致时仍判拒」的防御形态。
- 2026-09-17 SPEC 的既有通过用例（「无步骤无断言同文→仍拒」）需按新语义更新——属有意的行为变更，更新时保留混合组仍拒用例。