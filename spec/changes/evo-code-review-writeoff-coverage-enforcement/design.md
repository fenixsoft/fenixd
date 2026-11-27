## 设计

### 改动点

1. core/agent_runner/maintenance_runs.py（_writeoff_coverage_guard 及收尾资格门段 :3304-3465，含 :3416 旗标锚写入点）：
   - 守卫现有行为不变：计算覆盖并落 WARNING「核销锁定」。本次在其后加执行层，**仅作用于既有全仓核销分支**（`review_kind == "manual_full"` 或 `scheduled` 且 `window_start is None`；窗口档不参与，沿用只增不核销不变量）：
     - **缺口口径**：在守卫返回后于两分支（重派/普通）共用一处计算 `uncovered = origin_files - covered`、`gap_ratio = len(uncovered) / len(origin_files)`。`origin_files` 为空、manifest 缺失/损坏或判定异常（守卫已按锁定处理）时 **MUST NOT 按比例降格**（不做 0/0 除法，维持既有 WARNING/锁定，不新写锚、不发覆盖缺口信号）。
     - **阈值**：模块常量 `CODE_REVIEW_COVERAGE_GAP_THRESHOLD = 0.02`，**非配置项**（本仓约定：新增配置项须带 Dashboard 界面，不在本 SPEC 范围）。严格大于阈值才降格（`gap_ratio > 0.02`）；等于阈值按现行为 success。
     - a. **终态降格**：置独立标志 `coverage_demoted = True`，**不就地改写 `run_ok`**——`run_ok` 仍驱动既有 error 抢救分支、ratelimit/stall 重派意图登记与 code-fix 激活门，就地改写会误入这些路径。收尾构造 result 时：`CodeReviewResult(success=run_ok and not coverage_demoted)`，`error` 追加「覆盖缺口降格 partial：未覆盖 N/M（x%）」摘要，并在 result 对象上就地挂载 `coverage_partial=True` 与 `coverage_gap={uncovered, total, ratio, files[:5]}`（动态属性，与既有 `fail_face`/`ratelimit_redispatch`/`stall_redispatch` 同形态，不改 `result_gate.CodeReviewResult` 构造签名）。`_log_lane_run_metrics` 增**可选** `terminal` 形参（缺省沿用 `"success" if run_ok else "error"`），降格时传 `terminal="partial"`。
     - b. **告警**：复用既有 `AdminStore.append({kind: SIGNAL, ...})` 信号写回通道（对齐 `core/code_fix.py::_emit_signal` 形态），`signal_type="code_review_coverage_gap"`、severity=major，evidence 含 run_id、未覆盖数/总数/比例与前若干未覆盖文件示例。写前按同项目同类型「未处置」信号去重（对齐 `_signal_inflight` 口径），避免同一缺口逐轮刷信号。
     - c. **落锚**：调用 `core/code_review.py::write_pending_writeoff`（:2192 既有实现），payload `{run_id, reason: "coverage_gap", attempts, at, gap: {...}}`。**仅非重派 run（`redispatch_of is None`）新写锚**；重派 run（`redispatch_of` 非空）**MUST NOT 改指锚**——既有 :3416 注释同一不变量（重派链锚指向链根，改指链尾会丢根覆盖并弱化核销门）。锚内未覆盖清单只作留痕，续审扫描按「收集清单 − 锚 run 链累计覆盖」现算剩余，不依赖该字段。
     - d. **重试上限（写入侧收口，消费侧零改动）**：`coverage_gap` 锚携带 `attempts`。重派 run 收尾仍超阈值时：读锚，若 `anchor.run_id == redispatch_of` 且 `reason == "coverage_gap"`，在**原锚**上 `attempts += 1`（run_id 不变）；`attempts` 达到 `CODE_REVIEW_COVERAGE_GAP_MAX_RESUME = 2`（连续 2 轮续审未收敛）时调用 `clear_pending_writeoff` 清锚并升级告警「覆盖缺口连续 N 轮续审未收敛」，停止自动续审——清锚后锚续审扫描自然空转，次日/下个常规周期由每日调度兜底。error/restart 锚不带 attempts、不设上限，行为不变。
     - e. **幂等**：同一 run 只降格一次（守卫每 run 收尾仅执行一次）；锚判定以**同 run id** 为准（`read_pending_writeoff().get("run_id") == run_id`），**MUST NOT 用「锚在册」作幂等判据**——异 run 的陈旧锚（如昨夜 error 锚）不得抑制本轮降格与落锚。
     - f. **与既有锚写入点互斥**：同一收尾至多写一次锚；若 :3416 重启旗标锚已写（`_checkpoint_flag_present and not redispatch_of`），跳过本次 coverage_gap 写锚与 attempts 维护，仅保留降格/告警。
   - 缺口 ≤ 阈值时上述全部跳过，保持现行为（WARNING 留痕、success 终态、不落新锚）。
   - **收敛边界**：本 SPEC 的降格→锚→续审闭环只对 `scope=full` 成立；配置为 `window` 时续审 run 走窗口档，不参与全仓覆盖守卫，锚可能因「剩余清单为空」保持原位（与既有 error 锚同语义），本 SPEC 不新增处理。

2. agents/code-review.md（提示词）与 core/agent_runner/maintenance_runs.py（收尾对账）：
   - **前提更正**：`core/code_review.py` **没有批次派发逻辑**——分批与派子代理完全由 agent 自主决定（`agents/code-review.md:36`「manifest 大时你可以分批、可派子代理并行审查」，批号 N 由子代理自选）。框架侧只在收尾按「主产物 + 全部分片」聚合，故不存在「框架批次派发侧」可挂留痕；留痕点改为提示词侧计划声明 + 收尾对账。
   - **计划声明**：`agents/code-review.md` 要求 agent 在派发任何批次前，先把批次计划原子写入 `.fenix/code-review/plan-<run_id>.json`（数组元素 `{batch: "b<N>", files: [...]}`；不派子代理时写单批计划或空计划表示全自审），并同步扩写「唯一允许的写操作」边界（主产物 + 分片 + 该计划文件）。
   - **收尾对账**：`run_code_review` 收尾读 `plan-<run_id>.json`，与分片/主产物的实际覆盖对账：计划中存在但实际零结果行的批记「计划缺批」，落 WARNING 并计入覆盖缺口告警正文；计划文件缺失/损坏时留痕「无计划可对账」，不阻塞收尾。该对账**不改变**既有 success/partial 判定。

### 不改动

- 锚续审扫描消费侧（core/admin_monitor.py）零改动——「锚在册与否是唯一触发条件」的既有语义直接复用；重试上限在写入侧以清锚收口（锚不存在即自动停止），消费侧无需感知。
- `.fenix/runs` 的终态分类（`result`→`done`）不改：降格的可见面为 run_metrics `terminal="partial"`、`CodeReviewResult.success=False` + error 缺口摘要、告警、锚与完成日志；dashboard 运行列表仍显示 done（执行干净结束，覆盖降格是质量终态而非执行终态）。
- redispatch 链字段（redispatch_of）、writeoff 抢救红线、限流终局续跑等既有机制不动。

### 测试设计

tests/test_code_review_coverage_gate.py（新建）：构造 manifest scope 与分片/主产物夹具，覆盖：

- 非重派超阈值 → `success=False`、`coverage_partial=True`、run_metrics `terminal="partial"`、告警落账、锚写入（`reason="coverage_gap"`, `attempts=1`）；
- 低阈值与**等于阈值** → success 终态、不落锚、无缺口信号；
- origin 为空 / manifest 缺失或损坏 → 不降格，维持既有 WARNING 锁定；
- 重派 run 超阈值 → 不改指锚、原地递增 attempts；达上限清锚并升级告警；
- 异 run 陈旧锚在场 → 不抑制本轮降格（同 run id 才幂等）；
- 批次计划缺批对账 → WARNING/告警正文含「计划缺批」，终态判定不变；计划文件缺失 → 留痕但不阻塞；
- 回归既有 tests/test_code_review_salvage_writeoff.py 与 tests/test_code_review_night_resume.py，确认 error/restart 锚语义与夜间续跑行为不被破坏。
