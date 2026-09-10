# 设计：验证报告合成 fast-track 场景数据源回退（fix-verify-report-fasttrack-scenarios）

## Context

- fast-track 裁决结果文件 `.fenix-run-result.json` 的 schema（`core/fast_track_result.py`）：场景明细在 `verification.scenarios` 嵌套键；full 模式 tester 的裁决产物是 `report.json`（顶层 `scenarios`）+ 同样写 `.fenix-run-result.json`（顶层场景键，`verify_engine` 路径）。
- `core/verify_report.py` 现状：`synthesize_verification_report` 载入 `report = _load_report_json()` 与 `run_result = _load_run_result()`（专属副本优先、主树回退且 spec 匹配守卫已内建）；渲染层 `_render_scenarios_table(report)` 只读 `report["scenarios"]`。fast-track 无 report.json → 场景表恒空。
- 同根因已于 2026-09-05 修复于 Dashboard 读侧（`core/dashboard/data.py::parse_run_result_scenarios`，同名回退语义），本 change 把契约补齐到报告合成路径，两处语义保持一致。

## Goals / Non-Goals

**Goals**

- fast-track SPEC 的合成验证报告场景表完整（与 Dashboard 场景页签同源同量）。
- full 模式行为零回归（report.json 顶层场景优先不变）。
- 保持渲染层纯函数、无 IO 的既有分层。

**Non-Goals**

- 不改 fast-track 结果文件写入端 schema（agent 侧契约不动）。
- 不改 Dashboard 读侧（已修复）。
- 不改 verify-report-gate 闸门时序与 fail-closed 语义。
- 不处理 agent 主动写报告（非合成路径）的内容质量——合成器只兜底自己的渲染。

## Decisions

1. **回退读取在入口合成层完成，渲染层仍收纯参数**
   `synthesize_verification_report` 中：`report["scenarios"]` 缺失/为空/非法时，取 `run_result["verification"]["scenarios"]` 归一为场景列表后传给 `_render_scenarios_table`。
   *备选*：渲染函数内部做 IO 回退——否决，破坏纯函数分层（现签名只收 report dict，测试与下游复用依赖此约束）。
   *备选*：改 `_render_scenarios_table(report, run_result)` 双参——否决，调用点两处（合成器 395 行、豁免段同源），单点归一入参最小。

2. **复用 `_load_run_result` 的查找与守卫**（专属副本优先 → 主树回退 → spec 不匹配忽略），不另写查找逻辑。主树共享文件会被最新 fast-track run 覆盖，spec 守卫是防止串 spec 的既有防线，与 Dashboard 读侧一致。

3. **场景表为空不阻断**：两路皆缺时场景表留空、报告照常合成。阻断语义（结构化数据整体缺失）归 verify-report-gate 管，本能力不重复设闸——合成器数据全缺时 `synthesize_verification_report` 本就返回 `ok: False`（`report is None and run_result is None` 分支，不变）。

## Risks / Trade-offs

- [fast-track 场景条目字段与 report.json 场景 schema 有差异（如无 `evidence`/`step_results`）] → `_render_scenarios_table` 渲染已按缺省容错（`.get` 链）；实现时以真实 fast-track 副本（8 个存量 SPEC）离线渲染验证。
- [fast-track 场景 status 枚举含 `exempt`（SCENARIO_STATUSES）] → 场景表状态列原样显示该值，不新增枚举映射；与 Dashboard 读侧行为一致（前端未收录值原样显示）。
- [主树共享文件回退可能读到同 spec 的旧一轮结果] → 与现状同险（summary/bugs 同源），专属副本优先使实际命中概率低；不新增缓解。

## Migration Plan

纯读取端兼容，无迁移。部署即生效：存量 fast-track SPEC（8/8 专属副本在盘）下次合成即出完整场景表。回滚 = revert 单 commit，无状态残留。

## Open Questions

（无——schema、查找顺序、容错语义均已在归档能力与本次 Dashboard 修复中定型。）
