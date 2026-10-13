## Context

2026-10-06 核查（planner-judge-…-1791194247-a1/-r1 归档+runner.py/result_gate.py 现状）：
- 硬门：core/agent_runner/result_gate.py:489-520 `_check_artifact_json_file`，mtime < run_started_at - _ARTIFACT_FRESHNESS_GRACE_SECONDS 即拒，fail-closed；is_resumed_worktree 豁免仅 implementer/fast-track 透传，planner-judge 不豁免。
- 重试：core/agent_runner/runner.py:4208 `_handle_artifact_gate_retry` → [artifact-structural] 标签 → superseded + 30s 退避整体重跑（_in_place_retry_backoff_yield，runner.py:3968，预算 (30,60,120)），重试前不清理。
- 派发收口：run_planner（runner.py:1175）覆盖 core/pm_engine/verification/pipeline.py:833/:2341 两个派发调用点；快道（fastlane.py:107 读侧、judge_gate.py 两条合成快道）不经 run_planner。
- 留档先例：core/pm_engine/family.py:906-950 上轮 impl 结果快照 prev-impl-result.json（os.replace 原子写）。

## Goals / Non-Goals

- [x] judge 派发前单文件改名留档 + 陈旧残留重试前清理
- [ ] 不动硬门 fail-closed 语义；不动快道；不处理 tokens.json 台账缺口

## Technical Design

1. runner.py `run_planner` mode=="judge" 分支、两条派发路径汇合处：目标 .fenix-run-result.json 存在即 os.replace 改名为 prev-judge-result.json（仅该单文件；改名失败非致命，WARNING 留痕）。
2. runner.py `_handle_artifact_gate_retry`：命中 _ARTIFACT_ERR_STALE 进入原地重试前同步改名/删除陈旧文件（与 1 共用同一改名函数）。作用域收敛（2026-10-06 评审修补）：该通道为全 agent_type 通用（implementer/fast-track/spec-review/planner-plan 均流经，result_gate.py `_check_agent_result_artifact` 分派），改名/删除仅当 agent_type=="planner-judge" 且路径经 `planner_result_path(root, spec, "planner-judge")` 重建（MUST NOT 从 error 归因文案解析路径）；跨 spec 共享根文件 `.fenix/.fenix-run-result.json`（实现收尾契约唯一落点，family.py `_read_prev_impl_conclusions` 与快道争议读侧候选均读它）及其他 agent_type 产物 MUST NOT 被改名/删除。
3. 时序安全：快道读侧（fastlane.py:107）先于 run_planner 执行，改名不引入读侧竞态。
4. 防护：改名仅对 judge 结果文件，不触碰 report.json/tokens.json/verdict_cache.json 等跨轮累积产物；resumed-worktree 豁免语义不变。

## Open Questions

- prev-judge-result.json 是否需要轮数后缀防同轮多次重跑覆盖——首版单文件覆盖即可（先例同型）。
- 归档内容异质（2026-10-06 评审补记）：正常 plan→judge 流中，judge 派发时该路径现存文件常为本轮 planready 产物（planner-plan 双产物门同读 `.fenix-run-result.json` 此路径），改名会将其装入 prev-judge-result.json——judge 随后覆写同路径，功能无损；仅裁决重派路径（本案事故路径）归档的才是上轮裁决产物。v1 接受归档内容异质，不做内容甄别。