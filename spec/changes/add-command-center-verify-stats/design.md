# Design: add-command-center-verify-stats

## Context

指挥中心「验证」车道卡统计唯一来源是 `verify-` 前缀 run 文件（`core/agent_runner/run_files.py` 车道前缀映射），新版三段验证流水线（`agents.use_new_verifier=True` 默认；`core/pm_engine/engine.py` `_run_verification_pipeline` → `core/verify_engine/` 三段执行）全程不产该前缀 run——阶段 2 VerifyEngine 纯进程内执行（无 LLM、无 run 产物），阶段 1/3 的 planner run 归 planner-plan/planner-judge 卡。因此验证活动在指挥中心不可见。

产物现场（已核实）：`.fenix/verify-progress/<spec>/report.json`（每轮 `fs_ops.atomic_write_json` 原子覆盖，shape `{spec, timestamp, summary:{total,passed,warnings,failed,errors}, scenarios:[...]}`，`core/verify_engine/engine.py` `_save_report`）+ `.fenix/verify-progress/<spec>.json` 进度摘要（`_write_progress`：起始写 `0/total "开始执行"`、逐场景递增、终态写 `total/total "验证完成: …"`，env-abort 亦有写点）。

## Goals

- 只要启动验证（无论是否派 agent run），指挥中心验证卡即有统计：终态轮折入 runs/成功率/活动桶，在飞轮显示 working + SPEC 归属。
- 零误触发风险：纯读侧聚合，不新增任何写路径。

## Decisions

1. **读侧聚合 verify-progress（用户定稿），不写侧合成 run 文件**：`verify-` 前缀被 `engine.py` `_cancel_lane_runs`、`queue.py` verify 单飞在飞集合、`admin_monitor._RUN_PREFIXES` 失败计数消费，写侧合成须逐一防误触发，风险与改动面大；读侧聚合零消费方触碰。也不归并 planner-plan/planner-judge run——它们同时服务规划与判定，口径失真。
2. **runs 计 SPEC 数不计数轮次**：report.json 每轮原子覆盖、无轮次历史产物，读侧不造历史——窗内有终态验证产物的 SPEC 各计 1。口径限制如实记录于 spec（非缺陷：车道卡语义是「活动可见性」非审计台账，轮次审计走 spec-runs/时间轴既有通道）。
3. **success_rate 轮级执行口径**：`summary.errors==0 → done`、`errors>0 → error` 进既有分母；场景级 `failed` 是验证发现的产品缺陷（验证的产出而非执行的失败），不计入执行成功率——与 run 语义「派发执行是否成功」对齐。
4. **在飞信号 = 进度摘要 `done<total` + mtime 新鲜窗 15 分钟**：独立常量（模块级 `VERIFY_INFLIGHT_FRESHNESS = timedelta(minutes=15)`），对齐 admin_monitor `DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES`；单场景长批间隔实测 4-5 分钟（verify-activity-signal 既有实证），15 分钟防假阴性。在飞是「当下」状态，与窗口参数无关（同 run `IN_FLIGHT_STATUSES` 口径）。
5. **在飞归属走 attributables 空 run_id 条目 + 前端 3 行小改**：`shared.ts` `AttributableRun.run_id` 放宽可空、`activityLineState` 过滤器 `!!a.run_id` 放宽；渲染端 legacy 路径（shared.ts:343 已喂 `run_id: ''`）已实现显名不可点，渲染零改动。排序值取进度文件 mtime。
6. **折入既有字段、不新增响应键**：org 响应契约零变动，前端卡片结构零改动；实现为 aggregate_org 项目循环内的 `_verify_progress_stats(proot, ...)` 助读函数（同一单文件，纯函数便于测试）。
7. **归档剔除与脏数据防御复用既有口径**：archived_names 剔除同 run 循环规则；只认 `<spec>/report.json` 与同名 `<spec>.json` 两类形态，其余（`activities-all.yml` 等顶层杂项、spec 目录内 `parallel_plan.json`/`impl-result.json`/`prev-impl-result.json`/`screenshots/`）忽略；脏 JSON/缺 timestamp/summary 跳过。

## Non-goals

- KPI 端点（`aggregate_kpi`）不折入验证统计（需求范围=车道卡；KPI 口径变更留待后续需求）。
- 不做验证轮次历史留痕（写侧改造，违背决策 1）。
- 不动 verify_engine/pm_engine 任何写路径。

## Risks

- **在飞误判**：进度文件陈旧残留（daemon 崩溃残留 `done<total`）→ 15 分钟新鲜窗兜底；窗内恰无新写点且 daemon 已死的极端窗口会短暂误显 working，与 admin_monitor 既有阈值语义一致，可接受。
- **多项目路径**：聚合在 `_scoped_projects` 循环内按 `proot/.fenix/verify-progress/` 取数，与 run 聚合同构，无跨项目串数据风险。
- **前端类型放宽的连锁**：`run_id?: string` 后编译期弱化，渲染端已容忍空值（legacy 路径先例），评估无新增运行时分支。
