# Tasks: add-command-center-verify-stats

## Deliverables

```yaml
- path: core/dashboard/data/command_center.py
  kind: modify
- path: core/dashboard/static/src/pages/command-center/shared.ts
  kind: modify
- path: tests/test_command_center_aggregation.py
  kind: modify
- path: core/dashboard/static/tests/commandCenter.test.mjs
  kind: modify
```

## 1. 后端聚合与前端容错

- [x] 1.1 `core/dashboard/data/command_center.py` 新增 verify-progress 助读函数（建议名 `_verify_progress_stats(proot, archived_names, win_start, now_dt)`，纯函数）：扫 `<proot>/.fenix/verify-progress/`，只认 `<spec>/report.json`（shape `{spec, timestamp, summary:{total,passed,warnings,failed,errors}}`）与同名 `<spec>.json` 进度摘要（`{total, done, current}`）；返回每 SPEC 的终态轮（timestamp→datetime、errors→done/error 计数、活动桶落点）与在飞判定（`done<total` 且 mtime 落模块级常量 `VERIFY_INFLIGHT_FRESHNESS = timedelta(minutes=15)`）；脏 JSON/缺 timestamp/summary 跳过；report.json 先 stat mtime 粗筛再读正文（同 `_window_runs` 口径：today/7d 窗 mtime 早于 14 日界不读正文，window=all 不限；进度摘要 mtime 即在飞信号、单行小文件恒读）；已归档 SPEC（archived_names）剔除；目录内其余产物（`parallel_plan.json`、`impl-result.json`、`screenshots/`、顶层杂项 `.yml` 等）忽略
- [x] 1.2 `aggregate_org` 项目循环内折入助读结果到 verifier 车道卡既有字段：runs 相加（窗内有终态产物 SPEC 各计 1）、success/success_denom 按 `errors==0→done / errors>0→error`、activity_14d 按 timestamp 落桶、last_activity_ts 取 max；在飞条目使 status=working 并向 `st["inflight"]` 追加 `(mtime_dt, project, spec, "")` 形态归属；verify 折入与 archived_names 加载 MUST NOT 被既有 `if not rows: continue` 早退短路（助读调用置于早退判定之前或独立取数——run 产物为零或全部超 14 日粗筛外的项目仍须聚合 verify-progress）；车道卡装配处 inflight→attributables 既有过滤器（现 `if not spec or started_dt is None or not run_id: continue`）同步放宽为 project+spec 齐备即保留空 run_id 条目（spec 空剔除口径不变；run 侧条目恒带 run_id 不受影响），否则在飞 verify 条目在装配处被丢弃、spec.md 在飞 Scenario 无法达成；不新增 org 响应键、不改既有键语义；不触碰 `verify-` 前缀 run 写路径与消费方
- [x] 1.3 `core/dashboard/static/src/pages/command-center/shared.ts`：`AttributableRun.run_id` 放宽为可空（`run_id?: string`），`activityLineState` 主路径过滤器 `!!a.run_id` 放宽为容忍空 run_id（project+spec 在即保留）；渲染层零改动（legacy 路径 shared.ts:343 已喂 `run_id: ''`，渲染端已显名不可点）

## 2. 测试

- [x] 2.1 `tests/test_command_center_aggregation.py` 增补 verify-progress 用例（tmp 项目根构造产物，直调 `aggregate_org`）：①终态轮折入（runs+1、errors==0 进分母 done、场景 failed 不进分母、活动桶/last_activity_ts 正确、其他车道卡不受影响）；②在飞（进度 done<total 且 mtime 新鲜 → verifier working + inflight 归属含空 run_id、runs 不计、mtime 过 15 分钟窗回落 idle；含零 run 产物项目仍正常出 verify 统计的早退不短路对照）；③归档剔除与防御（archived SPEC 不计、脏 JSON 跳过、顶层杂项 `.yml` 忽略、不抛异常）；④窗口口径（today 窗外 timestamp 不进 runs 但 activity/last_activity 口径与 run 语义一致）
- [x] 2.2 `core/dashboard/static/tests/commandCenter.test.mjs` 增补用例：`activityLineState` 对 `attributables=[{project, spec, run_id: ""}]` 返回 `kind: 'specs'` 且条目保留（既有 `!!run_id` 过滤会丢弃的回归对照）；既有用例「脏元素防御（缺 spec/run_id 剔除；全脏视同无归属）」（commandCenter.test.mjs:206-223）中「空 run_id 单条 → `kind: 'running'`」断言与本变更方向相反，MUST 同步翻转该断言（改为保留条目出 `kind: 'specs'`）并相应更名用例——非仅增补

## 3. 回归验证

- [x] 3.1 全量回归绿：`python3 -m pytest tests/test_command_center_aggregation.py` 全绿 + `cd core/dashboard/static && npm test` 全绿 + `python3 -m pytest tests/ -k command_center` 无回归
