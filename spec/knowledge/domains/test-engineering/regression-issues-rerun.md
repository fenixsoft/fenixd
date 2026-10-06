# 定向子集回归触发链（错误/长耗时重跑）
<!-- knowledge: capability=regression-issues-rerun rev=1
     sources=spec/archive/2026-10-07-add-regression-issues-rerun -->

从项目页「测试回归」分面一键重跑最近快照中失败/错误与长耗时用例的定向子集：受理走文件信号、子集在 daemon 消费时点计算、不可定向时 fail-closed 回退全量，子集产物不构成全量回归证据。

## 规则

- 触发端点 `POST /api/regression/run-issues?project=<name>`：不消费请求体（与同族端点一致）；校验通过后原子写同一信号文件 `.fenix/regression_request.json`，payload 为 `{"source": "dashboard", "requested_at": <UTC ISO>, "scope": "issues"}`，返回 `200 {ok: true, requested_at}`。
- 守卫链与 `POST /api/regression/run` 一致且收敛为共享实现（MUST NOT 复制两份同构守卫），拒绝以稳定错误码表达：项目不存在 → 404；verify.yaml 无有效 regression 段 → 400 `regression_not_configured`；已有回归在跑（`.fenix/regression/.running` marker 新鲜度判定）→ 409 `regression_already_running`；daemon 未受 supervisor 托管/未运行 → 409/400（hosting 守卫，与 run 端点共用实现）；最近快照缺失/损坏/不可解析 → 400 `regression_never_run`；快照可读但 failures 与 long_tests 均空且 status 非 timeout → 400 `regression_no_issues`；信号文件已存在（并发第二 POST 或上一信号未消费）→ 409 `regression_request_pending`。任一拒绝 MUST NOT 写信号文件。
- 子集口径固定为「异常用例并集」：最近快照 `failures`（失败+错误）与 `long_tests`（长耗时）条目映射为 nodeid 后取并集、按 nodeid 去重（两表可能同例）；「整体超时」伪行非用例，不参与口径。不做用例级勾选/自定义子集。
- 子集计算归 daemon 消费端：`_check_regression_requests` 仅在 payload `scope == "issues"` 分支内经 `code_fix.map_snapshot_issues_to_nodeids(snapshot, exec_root)` 计算，以既有门面参数 `subset_nodeids` 派发；端点只做「快照有异常用例」的机械守卫。计算必须落在消费时点——映射依赖 exec_root 在盘测试文件探测，且快照可能在信号滞留窗口内被覆盖。
- fail-closed 回退：任一用例映射失败、映射结果为空、或命令非 pytest 形态（`_apply_pytest_subset` 返回 None）时，回退跑全量并记 WARNING 留痕——MUST NOT 静默漏跑用例、MUST NOT 派发空跑、MUST NOT 丢弃请求。时效分档（陈旧信号不执行）与单飞守卫沿用既有消费端语义不变。
- 向后兼容：payload 无 `scope` 键或 `scope` 未知时按全量消费（存量写手零迁移）；周期调度回归恒全量，不受本链影响；非 pytest 测试框架不做子集改写（走 fail-closed 回退）。
- `run_scope` 快照标记：当且仅当子集改写实际生效（`_apply_pytest_subset` 成功）时，本次运行落盘快照携带 `run_scope: "issues"`；回退全量的运行是真全量，快照 MUST NOT 携带该标记（门禁可正常采信）。全量触发落盘快照与既有字段完全兼容，读侧零迁移。
- full-suite 门不可见：门禁读侧对 `run_scope == "issues"` 的框架侧回归产物判本源不可见（fail-open 回落 run 自查值/既有逐级回落，不抛异常、不产生 error）；子集通过 MUST NOT 使 full-suite 门呈现 passed。终态豁免优先级不受影响。
- nodeid 映射以 classname 主导重构；映射条目 MUST NOT 携带 `file` 键——本项目 pytest junitxml 只产 `classname/name/time` 三属性，快照 `file` 是 classname 点分兜底，带入会被映射器的 file 一致性校验恒判不一致、映射恒失败。`long_tests` 条目须带 `classname`（`extract_long_tests` 已补齐）；旧快照 long_tests 缺 classname → 整体映射失败 → 回退全量（跑一次新全量后子集真正生效，不做迁移）。

## 关键行为

- 主链：分面点击「立即执行错误/长耗时回归」→ POST run-issues 守卫链校验 → 原子写 `scope=issues` 信号 → daemon 主循环消费 → 按最近快照计算 nodeid 子集 → `run_regression(subset_nodeids=...)` 派发 → 结果覆盖落盘 `last-run.json`（子集生效时带 `run_scope: "issues"`）。
- 单快照覆盖语义不变：子集结果覆盖 `last-run.json`，不新增历史留存；再跑一次全量即恢复全量口径。

## 溯源

- 2026-10-07 add-regression-issues-rerun（spec/archive/2026-10-07-add-regression-issues-rerun） — 新增定向子集回归触发链：run-issues 端点与共享守卫链、scope=issues 信号契约、daemon 消费端子集计算与 fail-closed 回退、run_scope 快照标记、full-suite 门对子集快照不可见、long_tests 条目补 classname 与 code_fix 公开映射封装
