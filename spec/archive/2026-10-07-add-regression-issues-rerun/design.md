## Context

「测试回归」分面（`RegressionTab.tsx`）当前只有「立即执行全量回归」手动触发：POST `/api/regression/run` → 原子写 `.fenix/regression_request.json` 信号 → daemon 主循环 `_check_regression_requests`（fenixd.py:3541）消费 → `agent_runner.run_regression(spec, reason="manual")` 门面 → `core/regression.run_and_write_regression` 按 verify.yaml regression.cmd 执行 → 单快照 `last-run.json` 覆盖落盘。

定向子集回归的底层机制已存在（add-codefix-targeted-retry）：

- `core/agent_runner/maintenance_runs.py` `run_regression(..., subset_nodeids=None)` 门面参数 + `_apply_pytest_subset`（把 pytest 命令既有收集位置参数替换为 nodeids，fail-closed 回全量）；
- `core/code_fix.py` `_map_junit_failures_to_nodeids(failures, exec_root)`（classname 主导 nodeid 重构，任一用例失败整体 ok=False）；
- 快照 `failures` 条目已带 `classname`（add-codefix-targeted-retry 1.1），但 `long_tests` 条目只拷 name/file/line/time、**无 classname**。

实测基线（fenixd 自托管，2026-10-02）：本项目 pytest junitxml 只产 `classname/name/time` 三个属性、不产 `file`；快照里 `file` 字段是 `_resolve_file` 的 classname 点分兜底（如 `tests.test_knowledge_audit`）。这决定 D4。

## Goals / Non-Goals

**Goals:**

- 分面一键重跑「失败+错误+长耗时」用例并集（口径用户已确认；整体超时伪行不可选）。
- 受理/运行态/进度条/轮询与全量按钮完全共用既有机制（同一信号文件、同一消费者、同一单飞与 marker）。
- 子集不可定向时 fail-closed 回退全量（宁可慢跑全量，不静默漏跑）。
- 子集快照 MUST NOT 被 full-suite 门采信为全量证据（防白洗通道）。

**Non-Goals:**

- 不做用例级勾选/自定义子集（只做「异常用例并集」这一种固定口径）。
- 不改单快照语义（子集结果覆盖 `last-run.json`，不新增历史留存）。
- 不为非 pytest 测试框架实现子集改写（沿用 `_apply_pytest_subset` 的 fail-closed 回退）。
- 不改周期调度回归（scheduled 路径恒全量）。
- 不动 quality-gates 其余 5 道门与状态枚举。

## Decisions

**D1 信号复用 + scope 键，不新增信号文件。** `/api/regression/run-issues` 写同一 `.fenix/regression_request.json`，payload 增 `"scope": "issues"`；消费端对无 `scope`/未知 `scope` 的信号按全量消费（向后兼容，存量写手零迁移）。新增独立端点而非给 run 加请求体：该族端点刻意「不消费请求体」（item 6e9597e51e90），独立路径让错误码面与契约各自独立；两端点重复的守卫链（404/400 未配置/409 在跑/hosting）抽 mixin 内共享 helper（对齐 item e22bfec7b9ee 的 `_write_trigger_signal` 收敛先例）。

**D2 子集计算放消费端（daemon），不放端点。** 端点只做「快照有异常用例」的机械守卫（`regression_no_issues` 拒绝，对齐 fix 端点先例）并写信号；nodeid 映射在 `_check_regression_requests` 的 `scope=="issues"` 分支内完成——映射依赖 exec_root 文件存在性探测（在盘测试文件），且快照可能在信号滞留窗口内被覆盖，消费时点计算才新鲜。

**D3 nodeid 映射封装放 code_fix、条目不带 `file` 键。** 新增公开薄封装 `code_fix.map_snapshot_issues_to_nodeids(snapshot, exec_root) -> (nodeids, ok)`：failures + long_tests 构造映射条目（long_tests 条目缺 `classname` 时该用例映射失败→整体 ok=False，fail-closed）、按 nodeid 去重（failures 与 long_tests 可能同例）。映射条目 **MUST NOT 携带 `file` 键**：本项目 pytest junitxml 不产 file 属性，快照 `file` 是点分 classname 兜底，带入会被 `_map_junit_failures_to_nodeids` 的 file 一致性校验判不一致、映射恒失败（该缺陷同时存在于既有 targeted-retry 路径，本 SPEC 不修其调用点，只在新增封装内规避）；非 Python 标识符形态 classname（jest-junit 等）本来就判失败回全量，无信息损失。

**D4 `extract_long_tests` 补带 `classname`。** 对齐 failures 侧 add-codefix-targeted-retry 1.1 的补齐做法（cases 侧本就携带）。旧快照 long_tests 无 classname → 映射整体失败 → 回退全量（D3 fail-closed 自然兜住）；跑过一次新全量后子集按钮即真正生效。前端「按钮可用性」不做 classname 预判（机械判定=表格有异常行），映射可行性归消费端日志。

**D5 快照 stamp `run_scope`，仅子集实际生效时。** `core/regression.run_and_write_regression`/`run_regression` 增可选 `run_scope: str = None`，非 None 时 stamp 进结果 dict 再落盘。门面（maintenance_runs）仅在 `_apply_pytest_subset` 改写成功时传 `run_scope="issues"`；回退全量的运行是真全量，不 stamp（门禁可正常采信）。门面日志文案「code-fix 定向子集回归」泛化为「定向子集回归」。

**D6 full-suite 门对子集快照判本源不可见。** `quality_gates._full_suite_product_status` 在 status 白名单判定前增一条：`data.get("run_scope") == "issues"` → `(None, "")`（fail-open 回落 run 自查值/既有逐级回落）。否则「子集 passed」会把 full-suite 门洗成 passed——与「空场景白洗通道」同类洞（治理记忆 fenixd-stale-dist-verified-whitewash 同族）。`read_progress` 的估算分母可能取到子集耗时：仅影响进度估算精度，不治理。

**D7 前端按钮与子集快照标识。** 概览卡按钮行「自动修复回归问题」与「立即执行全量回归」之间插入新按钮：`type="primary"`（蓝底白字，用户指定）、文案「立即执行错误/长耗时回归」、Tooltip「只重跑失败/错误/长耗时的用例；无法定向时自动回退全量」。可用性机械判定 = 快照 `failures` 或 `long_tests` 非空（与「自动修复」同款 span+Tooltip 禁用态范式）；`running`/`awaitingStart` 与全量按钮同口径禁用；受理成功同进 awaitingStart 过渡态（轮询/进度条天然接管）。快照 `run_scope=="issues"` 时概览卡状态 Tag 旁加「定向子集」Tag + secondary 说明（total 按子集口径；单快照覆盖语义，再跑全量即恢复）。

**D8 前端 service 层新增 `triggerRegressionIssues(project)`**（POST `/api/regression/run-issues?project=`，body 空对象与同族一致），`RegressionResult` 类型增 `run_scope?: string`。

## Risks / Trade-offs

- **映射失败静默感**：子集不可用时回退全量，用户感知是「跑得久」。缓解：按钮 Tooltip 预告回退行为 + 消费端 warning 日志留痕（对齐 targeted-retry 既有取舍）。
- **子集快照覆盖全量快照**：分面 total/计数在子集运行后按子集口径，可能被误读为「全量只有 N 例」。缓解：D7 的「定向子集」Tag + 说明文案明示口径。
- **旧快照首次点击回退全量**：fail-closed 的预期行为；跑一次全量后自愈。不做迁移。
- **并发窗口**：信号受理到消费之间快照被覆盖（如另一项目操作触发全量）→ 子集按最新快照计算，与用户点击时所见表可能不同。窗口极小（daemon 1s 主循环），接受。
