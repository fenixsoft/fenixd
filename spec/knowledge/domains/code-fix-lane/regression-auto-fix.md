# 回归问题一键自动修复

<!-- knowledge: capability=regression-auto-fix rev=1
     sources=spec/archive/2026-10-03-add-regression-auto-fix -->

测试回归分面的一键修复入口：把最近一次回归快照中的异常用例转换为 code-fix 台账条目并触发修复链，受理与判定结果回链到前端。

## 规则

### 前端按钮（测试回归分面）

- 「自动修复回归问题」按钮与「立即执行全量回归」并排渲染于概览卡右下按钮区。
- 按钮可用性由最近一次回归快照机械判定：快照存在且问题列表非空（`failures` 非空、`long_tests` 非空或 `status === 'timeout'`）才可点击；快照可读但无异常时按钮渲染但禁用（Tooltip「无异常用例可修复」）。
- `never_run` / `parse_error` 引导态视图不渲染本按钮（引导态只保留手动触发回归）。
- 触发在途（受理回链未返回）时按钮进入 loading 并禁用，重复点击不产生第二个信号。

### 触发与回链 API

- `POST /api/regression/fix?project=<name>`：校验项目存在（否则 404）与最近一次回归快照后，向项目根原子写信号 `.fenix/regression_fix_request.json`（`O_CREAT|O_EXCL` 独占创建，payload 恰为 `{source: "regression_fix", created: <ISO 时间戳>}`；信号已存在 → 409，不覆盖）。
- 稳定错误码拒绝且不写信号：快照缺失 / `never_run` / `parse_error` 损坏 → 400 `regression_never_run`；快照可读但无异常 → 400 `regression_no_issues`。
- `GET /api/regression/fix-result?project=<name>`：读 `.fenix/regression_fix_request_result.json` 原样返回；结果文件缺失返回 `{"status": "none"}` 形态，不 404 / 500。
- 前端点击后以 1s 间隔轮询回链（上限 30s），仅当结果 `request_created` 与本轮触发返回的 `requested_at` 一致才视为本次结果，陈旧残留不作数；轮询超时提示到进度卡片或 daemon 日志确认。触发成功后由质量页签既有修复进度卡片接管进度展示。

### daemon 消费与台账转换

- 主循环 `_check_regression_fix_requests` 以 1s 粒度经 `_consume_request_file` 原子消费信号（先 rename 占位再读，消灭「先读后删」窗口）；信号 JSON 损坏时删除防卡死、不落结果、不触发 checkpoint。
- 消费端读最近一次回归快照以当下为准，不与信号锁定：快照已被覆盖 / 清理 / 损坏即落 `triggered=false, reason=snapshot_missing`，不入账、不调 checkpoint、不重试不排队（单快照语义无历史可回放，用户重按即可）；信号不内联快照副本。
- 转换映射固化：`kind=failure` → category `regression-failure`、`kind=error` → `regression-error`（severity 均 high）；`long_tests` 逐条 → `regression-long-test`（severity medium）；title 取用例名；description 携带分类、耗时与失败 message（超长截断至 500 字）；suggestion 按类目固化文案。
- 整体超时（`status === 'timeout'`，无逐用例定位）转换为单条 `regression-timeout` 条目（severity high）：file 固定 `.fenix/verify.yaml`（回归硬超时声明的真实落点，作为修复入口锚点，不伪造用例路径）、title 固定「回归整体超时」、description 携带 reason 与输出摘要（消费端预读快照 output 字段指向的日志文件尾部，读取失败置空，截断 500 字）。
- 入账经 `upsert_findings`：`review_id` 取 `regression-fix-<信号 created>`、`review_kind` 固定 `regression_fix`（仅作元数据透传）；去重沿用 fingerprint（file+category+title）语义——同问题重复出现仅刷新 last_seen_at/severity/description/suggestion，不覆盖 status/first_seen_at。
- 复发重开：category 以 `regression-` 为前缀的条目若 fingerprint 仍在本次快照问题列表但 status 已非 open，消费转换时重开为 open 并刷新 first_seen_at（保证复发问题可再次触发修复，否则链以 no_open_items 拒绝、按钮一次性失效）；非 `regression-` 前缀条目（code-review 来源）MUST NOT 被此规则触碰，即使 file/title 恰好同名。
- 派发以 `override_enabled=True` 调 `checkpoint()`：手动触发即临时授权绕过 `enabled` 总开关；单飞（already_running）、失败保留、回归契约 fail-closed 等其余守卫原样保留，不因手动触发放宽。
- checkpoint 拒绝（如 `already_running`）不回滚已入账条目：条目保持已入账状态，由在飞链下一批 `select_batch` 自然吸收；结果如实记录 `triggered=false` 与 reason，不制造「条目消失、触发失败」假象。
- 编排器未装配 → `orchestrator_missing`；转换或 checkpoint 抛异常 → `dispatch_exception`（已入账条目不回滚）；均落结果文件，不静默丢信号。

### 结果回链

- 无论结果如何 MUST 原子写 `.fenix/regression_fix_request_result.json`：`{request_created, triggered, reason, message, finished_at}`，`request_created` 回链信号文件的 `created`，`message` 为面向用户的人类可读中文文案。

### 长耗时修复语义

- `regression-long-test` 条目的 suggestion 固化为：以不改变测试通过结果为前提，允许优化被测实现或测试代码本身（去冗余 sleep、修慢 fixture、并发化等）。
- 修复 Agent 对长耗时条目的处置 MUST NOT 使原测试由通过变为失败；批验证回归重跑若变为失败，按既有批失败语义处置。

## 溯源

- 2026-10-03 add-regression-auto-fix（spec/archive/2026-10-03-add-regression-auto-fix） — 新建本页：回归页签修复按钮与可用性机械判定、触发/回链 API 与稳定错误码、daemon 消费与快照→台账转换映射（含整体超时 verify.yaml 锚点、fingerprint 去重、`regression-` 前缀复发重开）、override_enabled 派发与 checkpoint 拒绝不回滚、长耗时修复语义固化。
