<!-- knowledge: capability=impl-regression-delegation rev=1 sources=spec/archive/2026-09-27-add-impl-selfcheck-model-probe -->

# 实现期全量回归委托

回归责任单点化：全量回归由验证链执行，implementer 收尾不再必跑；run 内执行是框架侧产物不可用时的降级路径，读侧按数据源优先级合成 `full-suite` 门。

## 现行规则

- 责任划分：全量回归由验证链执行；implementer 收尾检查注入段对全量回归的措辞为「全量回归由验证链执行；仅当确认框架侧回归产物不可用时才在 run 内执行并落盘」。frontend-build 与 interaction-contract 两项自查要求保持现状不变。
- 门禁 fail-open：框架侧（result_gate、交付物守卫等）不因 quality-gates.json 的 `full-suite` 项缺失或为 pending 而新增任何打回/失败终态（沿用 quality-gates 既有 fail-open 语义）。`full-suite` 键仅在 run 内实际执行回归（降级路径）时写入，未执行时不写该键；gate-id 全集、status 枚举与其余两键的落盘契约不变。
- 读侧数据源优先级：dashboard 的 `full-suite` 门判定按序取值——①框架侧回归产物（`core/regression.py` 产出、带分支指纹的回归结果快照；指纹校验对齐 ocr 门 `(branch, base, head_commit)` 语义，指纹陈旧按不可见处理）；②quality-gates.json 的 run 内自查值（存量与降级兼容来源）；③两者皆无 → pending。框架侧产物与自查值同时存在且结论不一致时，以框架侧产物为准。
- 容错：任一来源异常（文件损坏、字段缺失）fail-open 回落到下一优先级，不抛异常；`full-suite` 门状态枚举（passed/failed/running/skipped/pending/unknown）与 quality-gates.json 键名全集保持不变。

## 溯源

- [2026-09-27 2026-09-27-add-impl-selfcheck-model-probe](spec/archive/2026-09-27-add-impl-selfcheck-model-probe/) — 回归责任单点化：收尾措辞改为委托验证链、`full-suite` 键改为降级路径才落盘、读侧合成数据源两级优先级
