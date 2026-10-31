# 评审供给失败归因与车道韧性
<!-- knowledge: capability=spec-review-infra-attribution rev=2
     sources=spec/archive/2026-10-11-evo-fix-spec-review-infra-attribution-bridge,spec/archive/2026-10-27-evo-add-review-failure-attribution -->

spec_review 车道对供给类失败（限流、连接错误）的结构化归因传递、infra/content
二分处置（不烧评审预算 + 熔断冷却）、在飞并发上限与冻结文案红线。

## 规则

- **结构化归因传递**：spec_review 派发的 run 失败时，单轮 API 错误的结构化
  归因（`api_error_status`、连接类标记 `conn_error`、stderr 摘要
  `stderr_tail`）作为 `AgentRunResult` 的字段随结果对象传递到失败处理层；
  `run_spec_review` 的 catch-all 从异常回填 api_error_status 与 conn_error。
  失败分类（`_classify_run_failure`）优先消费结构化归因：
  `api_error_status=429` 或 `conn_error` 命中即判 infra；结构化字段缺席时
  回退既有文本指纹分类（`_INFRA_FINGERPRINTS` 词表与 429 数字正则），回退
  路径判定结果与既有口径一致。归因不得依赖经降噪的 stderr 文本——降噪后
  仅剩 `Exit code: 1`，文本匹配恒不命中。
- **失败行就地归因括注**：评审 run 失败的 ERROR 日志行 MUST 附加
  `[api_error_status=… exit_code=… stderr_tail: …]` 归因括注，形态与
  code-fix 车道一致；stderr_tail 复用既有 stderr 摘要助手读取异常
  stderr_lines——限流等供给类失败无须翻归档 run 文件即可就地归因。
- **infra 分支语义**：分类为 infra（供给瞬态）的失败不递增 `_review_attempts`
  （不计入 3 次评审尝试预算）、不进入冻结路径；由 infra 熔断器记账（阈值 3、
  冷却 30 分钟），达阈值武装冷却，冷却期内 `dispatch_review` 入口短路跳过
  派发，冷却期满自动重派。供给瞬态的自动恢复载体是熔断冷却，不转人工。
  评审 run 成功收工时调用 `record_success` 清零连续失败计数——「连续 infra
  失败」为窗口内连续语义，距上次成功多日后的偶发单次失败从 0 起算、不误触
  熔断；清零接线在评审链路收工点（语义是「链路证明可用」），熔断冷却短路
  期间未实际派发的尝试不计成功。
- **content 短退避**：content（评审质量）类失败重派前施加一档短延迟退避
  （秒级，判重 Timer 防重复定时器），两次重派间隔不再秒级连发；infra 分支
  不加退避——其节奏由熔断冷却负责，两类互不干扰。
- **评审车道在飞上限**：评审车道有在飞并发上限 `_REVIEW_INFLIGHT_CAP`
  （可配置，缺省 2-3），插入点在队列候选可派发判定；达上限时候选评审条目
  保留在队列中等待下轮派发（不 pop、不丢弃、无丢失），削掉批量晋升窗口的
  并发峰值。在飞上限以「队列保留条目」实现而非在晋升处打延迟定时器——
  定时器受 daemon 重启影响，队列保留天然幂等。
- **冻结文案按根因区分（三红线）**：评审自动冻结文案按根因取评审专用前缀
  （供给类 / 质量类分档），与「用户指令冻结」可区分——自动冻结不得自称
  用户指令。三条红线：
  1. 必须内嵌「原状态 reviewing」子串（`parse_orig_status` 解冻还原依赖）
     并保留 `spec-review-incomplete` 等既有标记子串；
  2. 不得命中 `_INTENTIONAL_PAUSE_MARKERS` 三短语、不得以 `frozen:`
     开头——不得挪用有意等待豁免；
  3. 仍经 `freeze_for_human` 成对入口落冻结与告警。
  `FREEZE_ERROR_PREFIX` 常量值不得修改：`freeze_spec` 人工冻结路径与
  `parse_orig_status` 文档契约依赖「用户指令冻结」前缀的有意豁免语义。
  冻结置 `frozen=True` 后被有意等待豁免命中属「冻结转人工」预期语义——
  冻结文案区分的目标是归因准确，不是逃过豁免。

## 关键行为

- 429 全链路：评审 run 因 `api_error_status=429` 终局（stderr 降噪后不可
  文本匹配）→ 结构化归因判 infra → 不递增尝试、不冻结 → 熔断器记失败，
  达阈值武装冷却 → 冷却期满 `dispatch_review` 自动重派。仅归因桥接即可使
  该形态失败不消耗评审预算、不产生冻结。
- 批量晋升削峰：短时间内多个 spec 同时晋升产生批量待派评审时，同一时刻
  在飞评审不超过上限，余量保留队列依次补位。

## 溯源

- 2026-10-11 evo-fix-spec-review-infra-attribution-bridge（spec/archive/2026-10-11-evo-fix-spec-review-infra-attribution-bridge） — 新增本页：结构化归因桥接（api_error_status/conn_error 优先、文本回退）、infra 分支不烧预算靠熔断冷却、content 重派短退避、评审在飞上限（可配缺省 2-3）、评审自动冻结文案三红线与 FREEZE_ERROR_PREFIX 不可动
- 2026-10-27 evo-add-review-failure-attribution（spec/archive/2026-10-27-evo-add-review-failure-attribution） — 修改本页：评审失败 ERROR 行补 api_error_status/exit_code/stderr_tail 就地归因括注（AgentRunResult 透传 stderr_tail）；infra 熔断计数接通成功清零（评审收工调 record_success，「连续」恢复窗口内连续语义，冷却短路期未派发不计成功）
