# 全仓审查覆盖缺口终态降格与续审武装

<!-- knowledge: capability=review-coverage-gap-enforcement rev=1
     sources=spec/changes/evo-code-review-writeoff-coverage-enforcement -->

全仓审查 run 收尾的覆盖缺口执行层：核销守卫算出真缺口但此前对账无执行面——缺口超阈值时终态降格、告警留痕、落 pending-writeoff 锚武装既有续审扫描自动补审，并以批次计划声明与收尾对账让「批次计划偏短」形态可直接判定。覆盖口径沿用核销守卫既有权威口径（分片+主产物聚合），核销红线本身不动。

## 规则

- **覆盖缺口阈值与终态降格**：仅在全仓核销分支（`manual_full` 或 `scheduled` 且 `window_start is None`；窗口档不参与，沿用只增不核销不变量）生效。未覆盖比例（`origin_files − covered`，覆盖取分片+主产物聚合）**严格大于** 2%（模块常量 `CODE_REVIEW_COVERAGE_GAP_THRESHOLD = 0.02`，非配置项）时：run_metrics `terminal="partial"`、结果 `success=False` 且 error 追加缺口摘要（未覆盖数/总数/比例）、result 挂 `coverage_partial=True` 与 `coverage_gap`；`.fenix/runs` 的 result→done 分类不变（执行干净结束，降格是质量终态而非执行终态）。`run_ok` 原值不动——就地改写会误入 error 抢救、限流/停滞重派意图登记与 code-fix 激活门。缺口 ≤ 阈值（含恰好等于）保持现行为：WARNING 留痕、success 终态、不落新锚、不发信号。
- **缺口不可判不降格**：`origin_files` 为空、manifest 缺失/损坏或覆盖判定异常时维持既有 WARNING 与核销锁定，不做按比例降格、不写锚、不发覆盖缺口信号（不做 0/0 除法）。同一 run 至多降格一次；幂等以同 run id 为准，异 run 的陈旧锚（如昨夜 error 锚）MUST NOT 抑制本轮降格与落锚。
- **覆盖缺口告警**：缺口超阈值经 AdminStore SIGNAL 通道落一条 `code_review_coverage_gap` 告警（major），正文含未覆盖数、比例与差集摘要（文件数过多给计数与前若干例）；同项目同类型未处置信号在场时不重复写。
- **coverage_gap 锚与续审武装**：落 pending-writeoff 锚（reason=`coverage_gap`，记本 run id），既有锚续审扫描据此自动武装 redispatch 补审。仅非重派 run（`redispatch_of` 为空）新写锚；重派 run MUST NOT 改指锚（链根不变量：改指链尾丢根覆盖并弱化核销门）。重派 run 收尾仍超阈值时在原锚上递增 `attempts`（run_id 不变），达 `CODE_REVIEW_COVERAGE_GAP_MAX_RESUME = 2` 清除锚并升级告警（`code_review_coverage_gap_unresolved`，「连续 N 轮续审未收敛」），停止自动续审，由下一个常规审查周期兜底；error/restart 锚不带 attempts、不设上限、行为不变。同一收尾与重启旗标锚命中时至多写一次锚，旗标锚优先。
- **批次计划声明与收尾对账**：分批与派子代理由审查 agent 自主决定（框架无批次派发逻辑），agent 在派发任何批次前 MUST 先把批次计划（批号 `b<N>` 与各批文件清单）原子写入 `.fenix/code-review/plan-<run_id>.json`，计划 MUST NOT 事后追加改写已声明批次；不派子代理时写单批计划或空计划（全自审）。run 收尾框架读该计划与「分片+主产物」实际覆盖对账：计划中存在但零结果行的批记「计划缺批」留痕并计入覆盖缺口告警正文；计划缺失/损坏留痕「无计划可对账」，不阻塞收尾。对账不改变 success/partial 终态判定，也不改变批次执行逻辑。

## 代码锚点

- 主实现：`core/agent_runner/maintenance_runs.py`（`CODE_REVIEW_COVERAGE_GAP_THRESHOLD`/`CODE_REVIEW_COVERAGE_GAP_MAX_RESUME`/`CODE_REVIEW_COVERAGE_GAP_SIGNAL`、覆盖缺口降格与告警、锚维护与 attempts 收口）
- 锚读写与续审扫描：`core/code_review.py`（write_pending_writeoff 读清三件套）、`core/admin_monitor.py`（锚续审扫描武装 redispatch）
- 提示词条款：`agents/code-review.md`（批次计划声明条款）
- 守卫测试：`tests/test_code_review_coverage_gate.py`

## 溯源

- 2026-11-27 evo-code-review-writeoff-coverage-enforcement（spec/changes/evo-code-review-writeoff-coverage-enforcement/） — 新建本能力：覆盖缺口 >2% 终态降格 partial + `code_review_coverage_gap` 告警 + coverage_gap 锚武装续审（重派递增 attempts、达 2 轮清锚升级 unresolved、旗标锚优先、异 run 陈旧锚不抑制）、批次计划声明 plan-<run_id>.json 与收尾「计划缺批」对账（动因：2026-11-21 夜审实测覆盖 311/362、真缺口 51 文件 14.1% 静默记 success 零告警，缺口延迟约 24h 才由次夜全量兜底且不可见）
