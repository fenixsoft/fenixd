# Spec Delta: command-center-aggregation — 验证车道 verify-progress 统计纳入

## ADDED Requirements

### Requirement: 验证车道 verify-progress 统计纳入

组织网格聚合（`aggregate_org`，`GET /api/command-center/org`）MUST 在既有 run 文件统计之外，读侧聚合每项目 `.fenix/verify-progress/` 产物并折入 verifier 车道卡既有字段，使新版三段验证流水线（VerifyEngine 进程内执行、不产 `verify-` run 文件）的验证活动在指挥中心可见。口径：

- **数据源**（每项目 proot，与 run 聚合同一项目循环）：`.fenix/verify-progress/<spec>/report.json`（终态验证轮，shape `{spec, timestamp, summary: {total, passed, warnings, failed, errors}}`）与 `.fenix/verify-progress/<spec>.json`（进度摘要，shape `{total, done, current}`）。
- **runs 计数**：口径 = 窗内有终态验证产物的 SPEC 数——`report.json` 存在且 timestamp 落窗的每个 SPEC 计 1，折入 verifier 卡既有 `runs` 字段（与 run 计数相加）。report.json 每轮原子覆盖、无轮次历史，同 SPEC 多轮仅代表最新轮（MUST NOT 造历史轮次）。
- **success_rate**：轮级执行口径——`summary.errors == 0` 记 done、`errors > 0` 记 error，进入既有 done/(done+error) 分母；场景级 `failed`（产品缺陷发现）MUST NOT 计入执行成功率分母。
- **activity_14d / last_activity_ts**：按 `report.json` 的 `timestamp` 落桶与取 max（进度摘要仅作在飞信号，不作活动源）；时间戳缺失/脏值防御性跳过该轮的活动贡献。
- **在飞状态**：进度摘要存在且 `done < total` 且文件 mtime 落新鲜窗（15 分钟，独立常量，对齐 admin_monitor 孤儿判定阈值；单场景长批间隔实测 4-5 分钟）→ verifier 卡 `status=working`，且 `attributables` 含 `{project, spec, run_id: ""}` 条目（started 排序值取进度文件 mtime）。新鲜窗外或 `done == total` 一律不判在飞。在飞条目 MUST NOT 计入 `runs`/success_rate/活动桶（终态产物才计）。
- **归档剔除**：已归档 SPEC（STATE.archive.md 清单）名下的 verify-progress 产物在全量窗（`window=all`）同样剔除，与既有 run 剔除口径一致。
- **防御**：目录内非 SPEC 产物（如无关 `.yml`、`parallel_plan.json`、`impl-result.json`、`screenshots/`）MUST 忽略；脏 JSON/缺关键字段（timestamp、summary）MUST 跳过该 SPEC，不冒异常、不中断聚合。
- **响应契约**：全部统计折入既有车道卡字段，MUST NOT 新增 org 响应键、MUST NOT 改变既有键语义；验证聚合 MUST NOT 触碰 `verify-` 前缀 run 的任何写路径与消费方（`_cancel_lane_runs`/verify 单飞/admin_monitor 失败计数）。
- **前端容错**：`AttributableRun.run_id` MUST 放宽为可空，`activityLineState` 主路径过滤器 MUST 保留空 run_id 的归属条目（渲染端既有 legacy 路径已将空 run_id 渲染为显名不可点，渲染层 MUST 零改动）。

#### Scenario: 终态验证轮折入车道卡

- **WHEN** 项目 fenixd 的 `.fenix/verify-progress/spec-a/report.json` 存在（timestamp=今日 10:00Z，summary={total:10, passed:8, warnings:0, failed:2, errors:0}），该项目今日另有 3 个 implementer run
- **THEN** window=today 下 verifier 卡 `runs=1`（折入后），success_rate 分母 +1 且 done +1（errors==0；场景 failed=2 不进分母），activity_14d 今日桶 +1，last_activity_ts=该 timestamp；implementer 卡统计与改动前逐字节等价

#### Scenario: 在飞验证显示 working 并归属 SPEC

- **WHEN** spec-b 验证进行中：`.fenix/verify-progress/spec-b.json` 存在（done=3 < total=14）且 mtime 距今 2 分钟，spec-b 尚无 report.json
- **THEN** verifier 卡 `status=working`，`attributables` 含 `{project, spec: "spec-b", run_id: ""}`，点击该 spec 名不打开运行记录弹窗也不报错；`runs` 不含 spec-b（无终态产物）；进度 mtime 超过 15 分钟新鲜窗后同状态回落 idle

#### Scenario: 归档剔除与脏产物防御

- **WHEN** window=all，目录下同时存在：已归档 SPEC 的 report.json、spec-c 的脏 JSON report、无关顶层文件 `activities-all.yml`、spec-d 的合法 report
- **THEN** 已归档 SPEC 与 spec-c 均不折入统计，`activities-all.yml` 被忽略，spec-d 正常计 1；聚合不抛异常，其余车道卡输出与改动前等价

#### Scenario: 前端空 run_id 归属条目保留

- **WHEN** verifier 卡 `attributables=[{project, spec, run_id: ""}]` 且 status=working
- **THEN** `activityLineState` 返回 `kind: 'specs'` 且该条目保留（不再被 `!!run_id` 过滤丢弃），渲染为显名不可点（复用 legacy 空路径渲染）
