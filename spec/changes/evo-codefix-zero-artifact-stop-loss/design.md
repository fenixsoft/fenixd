# 设计：codefix-zero-artifact-stop-loss

> 定位约定：主干并发演进使行号快速漂移（起草当日实测 core/code_fix.py 两轮读取间 7461→7578 行），本节一律以符号定位；行号仅为起草时快照，实现以符号检索为准。

## 落点

1. core/agent_runner/maintenance_runs.py（run_code_fix 收尾「产物硬门」块，`_check_code_fix_artifact` 调用点）：判定零产物失败时在 CodeFixResult 信封置 failure_category="artifact_missing"，随既有失败信封路径返回。CodeFixResult 类定义于 core/agent_runner/result_gate.py（maintenance_runs 导入沿用，既有 import 路径不变），新增字段 MUST 带缺省值——信封在本函数有多处构造点（早退失败与正常收尾），缺省空值保证未走硬门的构造点零触碰。
2. core/code_fix.py（`CodeFixChain._run_batch_inner` 首轮 `run_code_fix` 失败收尾块——run 失败→chain_skipped 瞬态、consumed 推进）：读取信封 failure_category，按批指纹累计 artifact_missing 连败（进程内跨链计数，见 D1；形态对齐回归异常熔断 anomaly_streak 先例但窗口更大）；≥2 触发止损：该指纹标记跳过＋WARNING/告警留痕。
3. agents/code-fix.md：只读引用，作为契约测试的断言对象（「并行处置」派发/等待契约段，9ccf90158/4c2fc3a9d 现状基线）。
4. tests/test_codefix_zero_artifact_breaker.py（新建）：
   - 信封类别透出单测（伪造硬门零产物失败）；
   - 止损状态机单测（1 次不触发/2 次触发/其他类别不计数/触发后跳过并留痕）；
   - agents/code-fix.md 契约断言（参照 tests/test_prompt_lane_efficiency_sections.py「长任务前台等待」段先例，按字面子串断言）。

## D1. 止损跳过标记载体与生命周期

- 载体 = **进程内指纹跳过集**（链编排器实例级）。MUST NOT 复用 `chain_skipped` 承载——后者「新链启动重置」（FIX_PROGRESS 语义），同指纹下一链立即重新入选，止损对「跨链/跨编排 run 连败」这一目标事故形态形同虚设。
- 选批排除并集（失败档案 ∪ chain_skipped，选批处）纳入该集合：触发后同指纹下一链不再入选派发，链内其余指纹不受影响。
- 留痕经既有 WARNING 日志/告警通道：含指纹、连败次数、最后失败 run id；不新增告警通道（proposal 非目标）。
- 计数窗口 = daemon 进程内跨链累计、同批次指纹；daemon 重启清零——重启后的残余重试面由既有失败档案 fail_count/FAIL_RETRY_MAX 预算兜底（与 add-codefix-parse-error-breaker D4「跨链重试由既有预算兜底、两层机制正交」同口径）。
- 计数域 = 仅首轮 run 失败收尾块；定向重试轮 run 失败（`regression_retry_run_failed` 收尾）沿用既有 chain_skipped 语义、不进该计数。

## 风险与权衡

- 与 add-codefix-parse-error-breaker（**已归档落地**：spec/archive/2026-10-28-add-codefix-parse-error-breaker，其 anomaly_streak 已实现于 core/code_fix.py 回归异常熔断 `_is_regression_anomaly`/`_anomaly_breaker_threshold`）同域不同类（parse-error vs artifact_missing），且二者连执行阶段都互斥：artifact_missing 发生在首轮 run 未产出、回归根本未执行之时；anomaly_streak 计数位于回归失败后的定向重试循环内。计数互不干扰，避免误伤合法重试。
- 与已归档 evo-run-failure-classification-circuitbreaker（review 车道 infra 级失败三级分类＋熔断冷却＋持久化 breaker 状态 .fenix/admin_infra_breaker.json）机制相邻但车道、失败类、作用域均不同（本 SPEC 止损为进程内批指纹粒度、不新增持久化状态文件），无冲突、不复用其状态，谨防后续被误并或重造。
- 止损只停「同指纹零产物」形态，不影响其他失败类的既有重试预算。
- 指纹粒度沿用批链既有指纹定义（批条目集），不新造指纹体系。
