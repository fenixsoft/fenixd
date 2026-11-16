# Design: fix-dashboard-verdict-fallback — Dashboard 验证裁决兜底读取 impl-result 快照

## Context

2026-11-07 排查确认：连续 5 个 fast-track SPEC 在 Dashboard 无验证记录，根因是兜底读取器候选链与 fast-track 收口快照命名脱节：

- 写侧：fast-track 收口共用段 `_fast_track_snapshot_and_cleanup`（`core/pm_engine/dispatch/fast_track.py:606`）在 merge 成功时点经 `_write_impl_result_snapshot`（`core/pm_engine/engine.py:2339`）把结果 dict 原子快照到 `.fenix/verify-progress/<spec>/impl-result.json`，随后删除主树共享 `.fenix/.fenix-run-result.json`（stamp 严格匹配才删）。
- 读侧：`core/dashboard/data/artifacts.py:202` `_load_run_result` 候选仅两路 `.fenix-run-result.json`（2026-09-16 引入 `_verdict_from_run_result` 兜底时的口径）；快照命名 2026-09-07（fix-verified-gate-evidence-race）即定为 `impl-result.json`，兜底自始未覆盖。
- 验证确实发生：受影响 SPEC 的 `impl-result.json` 均含 `verification.verdict=verified` 与逐场景 pass 明细（实测 add-spec-list-mobile-style 10/10 pass）。

## Goals

- 历史 fast-track SPEC 与未来 fast-track SPEC 的验证结论在 Dashboard 列表「验证」列 Popover 与详情页 VerdictPanel 恢复展示。
- 单文件读侧修改，不触碰验证/裁决写链、不改裁决语义、不产生 `verification-report.md`。

## Decisions

**D1 候选链三路化（核心改动）**：`_load_run_result` 候选列表在私有 `.fenix-run-result.json` 之后、共享 `.fenix/.fenix-run-result.json` 之前插入 `Path(project_root) / ".fenix" / "verify-progress" / spec_name / "impl-result.json"`。优先级理由：fast-track 因 bug-found/预算升级改写 `mode: full` 后（fast-track-mode 知识页既有规则），full 车道验证会在候选 1 落新裁决——新裁决必须压过 fast-track 期旧快照；共享候选垫底维持既有语义（须 `spec` 字段严格匹配，防他 spec 残留误合成）。

**D2 快照归属校验**：`impl-result.json` 候选与共享候选同口径做 `data.get("spec") == spec_name` 严格校验（实测快照顶层含 `spec` 键；`_write_impl_result_snapshot` 整体落盘收口 dict，字段在）。缺失/不匹配/损坏（JSONDecodeError/OSError/UnicodeDecodeError/非 dict）一律 fail-closed 跳过该候选继续下一路——对齐函数既有「缺失/非法返回 None」语义。

**D3 裁决提取零改动**：命中快照后沿用既有 `_run_result_verdict_and_bugs`——它已按 fast-track 形态读 `verification.verdict`/`verification.bugs`，非法裁决值 fail-closed 返回空串；`_verdict_from_run_result` 的三桶计数合成（int 形态、warning/exempt 不入桶、`product_bugs=len(bugs)`、`env_issues=None`）原样生效。docstring 契约段（str|int|None 三态，test_verify_report_gate / test_dashboard_data 断言钉死）不受影响，仅候选链扩一路。

**D4 测试落点**：`tests/test_dashboard_data.py` 新增 fast-track 快照路径用例组（命中渲染 / 升级 full 后候选序 / 归属不符忽略 / 损坏跳过 / 无裁决值 fail-closed），夹具按 `impl-result.json` 真实形态（`spec`+`verification.verdict`+`verification.scenarios[].status`）构造；既有 `_verdict_from_run_result` 两路用例不动。

## Risks

- [读侧性能] `parse_verdict` 在列表页逐行调用，候选从 2 路增至 3 路增加一次 stat——候选序不变命中即短路，绝大多数 SPEC 仍在前两路或直接落 md 解析路径，增量可忽略（仅 fast-track 无 md 场景多一次 stat 命中）。
- [形态漂移] `impl-result.json` 若未来写入侧改字段（如 `spec` 键更名）会静默失效回空态——D2 的 fail-closed 语义保证退化为「无记录」而非误报，与现状同代价；不做写读双向耦合。
- [历史缺口] `.fenix/verify-progress/` 受产物保留策略治理，个别老 SPEC（如 add-run-prompt-viewer）快照已不在——此类属既有保留策略语义，本 SPEC 不做历史回填。

## Migration

无数据迁移、无配置变更；部署后 daemon/Dashboard 进程重启即生效（读侧代码热路径，无状态）。
