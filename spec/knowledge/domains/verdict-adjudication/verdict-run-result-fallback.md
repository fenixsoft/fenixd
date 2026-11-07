# Dashboard 验证裁决兜底读取（结果文件三路候选）

<!-- knowledge: capability=verdict-run-result-fallback rev=1
     sources=spec/changes/fix-dashboard-verdict-fallback -->

Dashboard 裁决展示的读侧兜底链：`verification-report.md` 缺失时（fast-track SPEC 不产报告），从结果文件裁决段恢复验证结论供列表「验证」列 Popover 与详情页 VerdictPanel 展示，三路候选固定优先级、归属 fail-closed、不伪造结论。

## 规则

- **入口与分工**：裁决展示统一由 `parse_verdict`（`core/dashboard/data/artifacts.py`）供数——优先解析 `spec/changes/<spec>/verification-report.md`；报告缺失或不可解析时回退结果文件裁决段（`_load_run_result` 单点封装，多处读侧共用避免口径漂移）。兜底链只读，不触碰验证/裁决写链，不生成 `verification-report.md`。
- **三路候选固定优先级**（命中即返回）：
  1. `.fenix/verify-progress/<spec>/.fenix-run-result.json` — full 模式验证落盘的私有裁决副本；
  2. `.fenix/verify-progress/<spec>/impl-result.json` — fast-track 收口的 per-spec 实现快照（含 fast-track 嵌套形态验证段 `verification.verdict`/`verification.bugs` 与顶层 `spec` 字段）；
  3. `.fenix/.fenix-run-result.json` — 主树共享结果文件（兼容兜底，须顶层 `spec` 字段与当前 SPEC 严格相等）。
- **候选序即裁决权威序**：私有 run-result 压过 impl-result 快照——fast-track 因 bug-found 或预算升级改写 `mode: full` 后，full 车道落盘的新裁决必须压过 fast-track 期遗留快照；共享候选恒垫底，防他 spec 残留被误合成成本 SPEC 裁决。
- **归属 fail-closed 校验**：候选 2/3 均做顶层 `spec` 字段严格校验；字段缺失、不匹配、文件损坏（非法 JSON / 非 dict 形态 / 解码错误）一律视为候选缺失，跳过该路继续下一路，不抛异常、不中断响应。全部未命中返回空。
- **空态语义（不伪造结论）**：全部候选未命中，或命中文件缺合法裁决值（`verification.verdict` 缺失/取值非法）时，`parse_verdict` 返回 `exists: False` 空态——无裁决永远不得呈现为「已验证」；退化为「无记录」而非误报是有意形态。
- **裁决语义与形态契约沿用既有**：裁决值提取复用 `_run_result_verdict_and_bugs` 单点（兼容 fast-track 嵌套形态）；三桶计数合成为 int 形态契约（含 0、`product_bugs=len(bugs)`、`env_issues=None`）；docstring 的 str|int|None 三态契约与既有测试断言钉死不变；三路候选共用同一裁决提取与计数合成语义。
- **不做写读双向耦合与历史回填**：快照命中依赖写侧收口快照（fast-track merge 成功时点原子落盘并清理共享 run-result，见 [fast-track 模式](../spec-lifecycle/fast-track-mode.md)）；读侧不反推写侧字段、不做快照字段更名的双向适配。`.fenix/verify-progress/` 受产物保留策略治理，快照已清理的老 SPEC 呈空态属保留策略语义，非读取缺陷。

## 关键行为

`parse_verdict` → md 解析 → 缺失时 `_verdict_from_run_result` → `_load_run_result` 逐路尝试（路径 stat 命中即短路）→ 候选 2/3 做 `spec` 归属校验 → `_run_result_verdict_and_bugs` 提取裁决值与 bugs → 合成三桶计数 → `exists` 布尔返回。列表页逐行调用 `parse_verdict`，候选序不变命中即短路，绝大多数 SPEC 在 md 路径或前两路命中，仅 fast-track 无 md 场景多一次 stat，增量可忽略。

## 溯源

- 2026-11-07 fix-dashboard-verdict-fallback（spec/changes/fix-dashboard-verdict-fallback/） — 新增本能力：兜底读取器候选链二路扩三路（补 fast-track `impl-result.json` 快照候选与归属校验），修复成功收口的 fast-track SPEC 在列表与详情页恒空态、验证实际已发生却呈现「无验证记录」的覆盖缺口；裁决提取与三桶契约零改动。
