# design — run-failure-classification-circuitbreaker

## 现状

- spec_review.py:427-466 _handle_review_failure 不分类、机械递增至 MAX_REVIEW_ATTEMPTS=3 → freeze_for_human。
- admin_alerts.json 事件窗口无评审失败类（103 条告警类型集合实证）。

## D1 失败分类

- **硬依赖 evo-run-failure-artifact-first**（当前仍 drafted，.fenix/STATE.md:5448）：其
  `_artifact_landed_valid` 与 `_classify_run_failure` 须先落位；该 SPEC 未实现时 artifact
  分支回退 content。
- 复用/扩展 evo-run-failure-artifact-first tasks 1.3 的 `_classify_run_failure(reason)`
  （沿用同名，禁止另开 `_classify_failure` 并行实现；若其未落位则在本 SPEC 内以同名新建）
  → 扩展为三分 "artifact" | "infra" | "content"：
  - artifact：产物已落盘合法（调用 `_artifact_landed_valid`）；优先级最高；
  - infra：指纹匹配（403/402/429/quota/budget/余额/insufficient balance/rate limit/
    既有 provider 熔断信号 "provider circuit open" / "provider chain exhausted"——
    runner.py:2458/2473，供侧熔断同属 infra）或 CLI 进程级崩溃；
  - content：其余（含空白轮次）。
- **与既有 ProviderCircuit 互补**（provider_circuit.py:26 `PROVIDER_CIRCUIT_4XX=400/401/403/404`，
  同 threshold=3/cooldown=30min，进程内存不落盘）：本链路级熔断补齐其未覆盖的
  402/429/quota/budget 类 + 持久化 + 链路告警；403 双计无害（链路计数仅聚合告警，不抑制派发）。
- **v1 范围**：计数/短路/告警接驳仅 spec-review 链路（spec_review.py 失败收口处）；
  verify/impl 链路的失败收口接驳留后续 SPEC（分类函数保持链路无关可复用）。

## D2 熔断状态

- core/pm_engine/engine.py：链路级熔断器 {link: (count, until)}；连续 infra 失败 ≥3（admin.run_infra_breaker.threshold，默认 3）→ 熔断 until=now+cooldown（默认 30min）。
- **短路点（v1 仅 spec-review 链路）**：评审派发入口 `_on_spec_reviewing`（engine.py:263）
  与 `dispatch_review`（spec_review.py:46）短路，熔断窗口内直接返回不派发；verify/impl
  链路接驳留后续（见 D1 范围声明，防「声称三链路、实交一条」的空洞）。
- **infra 失败分支的 STATE 副作用**（_handle_review_failure 内）：清 reviewer_run、
  **不递增 _review_attempts**（熔断前与冷却期均不计入——infra 属链路级问题而非 spec 内容
  问题；若递增，第 3 次 infra 会同时触 MAX_REVIEW_ATTEMPTS=3 freeze 破坏「冷却后自动
  恢复」；若不清锚点，冷却到期后 dispatch_review 见 reviewer_run 非空拒派
  （spec_review.py:67-69），spec 永久卡 reviewing）。
- 状态持久化到 .fenix/admin_infra_breaker.json（daemon 重启后恢复，防止重启重置熔断；
  文件损坏/不可读按熔断复位 fail-open，不阻塞派发）。

## D3 ADMIN 信号接入

- core/admin_monitor.py：新信号类型 run_infra_failure（severity=critical）登记 SIGNAL_SEVERITY/SIGNAL_RECOMMENDATION；熔断触发/恢复各落一条记录，evidence 含链路/指纹/次数/时间窗（汇总口径：把同型失败次数并入，供人工一眼看出「评审 API 批量失败」）。
- **告警落盘与消费路径（防静默丢失）**：熔断触发记录直接落 kind=ESCALATION（critical，
  attach_trigger），**不唤起 Administrator**——评审链路 infra（403/402/budget）对 admin 无
  操作杠杆（spec_review.py:76-79 既有结论），唤起即烧 token 空转；恢复记录落 SIGNAL 档。
  若实现改走 kind=SIGNAL + admin_monitor 摄取唤起，须同步把 run_infra_failure 补入
  STORED_SIGNAL_TYPES（admin_monitor.py:168），否则重演 verify_uniform_failure「记录落
  store 无人摄取」的静默丢失（admin_monitor.py:175-183 事故注释）。

## D4 恢复

- 冷却到期自动恢复（窗口滑动）；恢复后首次成功 run 清空计数。

## D5 配置

- core/config.py admin 段新增：admin.run_infra_breaker.threshold（默认 3）、admin.run_infra_breaker.cooldown_minutes（默认 30）。