# impl-regression-delegation 能力增量（add-impl-selfcheck-model-probe）

> 回归责任单点化契约：全量回归由验证链执行，implementer 收尾不再必跑；full-suite 门数据源切换为「框架侧回归产物优先 + run 内自查降级兼容」，状态语义与键名全集零变化。

## ADDED Requirements

### Requirement: implementer 收尾自查的回归降级路径

implementer 收尾检查注入段（`prompt_builder.py`）对全量回归的措辞 MUST 从「必跑并落盘」改为「全量回归由验证链执行；仅当确认框架侧回归产物不可用时才在 run 内执行并落盘」。frontend-build 与 interaction-contract 两项自查要求 MUST 保持现状不变。框架侧（result_gate、交付物守卫等）MUST NOT 因 quality-gates.json 的 `full-suite` 项缺失或为 pending 而新增任何打回/失败终态（沿用 quality-gates 既有 fail-open 语义）。本条隐含修订 add-quality-gates-visibility「quality-gates.json 落盘契约」的「收尾 MUST 写入 3 项」条款：自本 SPEC 起 `full-suite` 键仅在 run 内实际执行回归（降级路径）时写入，未执行时不写该键（读侧按 pending 呈现）；gate-id 全集、status 枚举与其余两键的落盘契约不变。

#### Scenario: 不跑回归可正常收工

- **WHEN** 某 impl run 未在 run 内执行全量回归、quality-gates.json 仅落盘 frontend-build 与 interaction-contract 两项即收工，且实现与任务申报均无其他缺口
- **THEN** 收工硬门正常放行（full-suite 缺项不产生打回），读侧该门按数据源优先级呈现（见下一条 Requirement）

#### Scenario: 降级路径仍可用

- **WHEN** 某轮验证链被冻结/跳过导致框架侧回归不会执行，implementer 据此确认后自行跑回归并落盘 `gates["full-suite"]`
- **THEN** 该落盘值被读侧采信（降级兼容来源），门禁呈现与现状一致

### Requirement: full-suite 门数据源优先级（读侧合成）

Dashboard 读侧 `full-suite` 门判定 MUST 按以下优先级取值：①框架侧回归产物（`core/regression.py` 产出、带分支指纹的回归结果快照；指纹校验对齐 ocr 门 `(branch, base, head_commit)` 语义，指纹陈旧按不可见处理）；②quality-gates.json 的 run 内自查值（存量与降级兼容来源）；③两者皆无 → pending。任一来源异常（文件损坏、字段缺失）MUST fail-open 回落到下一优先级，MUST NOT 抛异常。`full-suite` 门的状态枚举（passed/failed/running/skipped/pending/unknown）与 quality-gates.json 键名全集 MUST 保持不变（`quality-gates-progress` 能力的读侧合成 Requirement 由此 delta 扩展数据源，其余条款不变）。

#### Scenario: 框架侧产物优先

- **WHEN** 某 spec 已完成验证轮，框架侧回归产物（指纹匹配当前分支）与 run 内自查值同时存在且结论不一致（产物 failed / 自查 passed）
- **THEN** 读侧 full-suite 门呈现 failed（以框架侧产物为准），detail 可溯源到产物路径

#### Scenario: 双源皆无呈现 pending

- **WHEN** 历史 spec 既无框架侧回归产物、quality-gates.json 也无 full-suite 项
- **THEN** 该门呈现 pending（fail-open），不抛异常、不影响其余 5 道门的呈现
