# spec-review-infra-attribution 规格

## ADDED Requirements

### Requirement: 供给类失败的结构化归因传递
spec_review 派发的 run 失败时，单轮 API 错误的结构化归因（api_error_status、连接类标记）SHALL 随结果对象传递到失败处理层，SHALL NOT 仅依赖经降噪的 stderr 文本；失败分类 SHALL 优先消费结构化归因，文本分类作为回退。

#### Scenario: 429 限流判 infra
- **WHEN** 评审 run 因 api_error_status=429 终局（stderr 文本被降噪到不足以文本匹配）
- **THEN** _classify_run_failure 判为 infra，_review_attempts 不递增，infra_breaker 记失败并在达阈值后武装冷却

#### Scenario: 文本回退仍生效
- **WHEN** 失败无结构化归因但 error 文本命中既有 infra 指纹（rate limit / 429 数字等）
- **THEN** 文本分类回退路径维持现状判定结果

### Requirement: 评审车道在飞上限
评审车道 SHALL 有在飞并发上限（可配置，缺省 2-3）；达上限时候选评审条目 SHALL 保留在队列中等待下轮派发，SHALL NOT 丢弃或并发超限。

#### Scenario: 批量晋升削峰
- **WHEN** 短时间内 8 个 spec 晋升产生 8 个待派评审
- **THEN** 同一时刻在飞评审不超过上限，余量保留队列依次补位

#### Scenario: 上限不丢任务
- **WHEN** 评审条目因达上限暂缓
- **THEN** 该条目仍在队列中，后续轮次正常派发，无丢失

### Requirement: 评审质量失败重派短退避
content（评审质量）类失败的重派 SHALL 在重派前施加短延迟退避（带判重，避免重复定时器）；infra 类失败的节奏 SHALL 仍由既有熔断冷却负责，两类互不干扰。

#### Scenario: 质量失败不再秒级连发
- **WHEN** 某 spec 连续 content 失败进入重派
- **THEN** 两次重派间隔不小于配置的短退避，不再出现秒级三连败

### Requirement: 冻结文案按根因区分且人工冻结契约不变
评审自动冻结文案 SHALL 按根因使用与「用户指令冻结」可区分的评审专用前缀（自动冻结不得自称用户指令），SHALL NOT 命中 _INTENTIONAL_PAUSE_MARKERS 三短语或以 "frozen:" 开头（不得挪用有意等待豁免），且 SHALL 保留「原状态 reviewing」子串供 parse_orig_status 解冻还原、SHALL 仍经 freeze_for_human 成对入口落冻结与告警；freeze_spec 人工冻结路径的既有前缀与豁免语义 SHALL NOT 改变。供给瞬态类失败（结构化归因判 infra）SHALL NOT 进入冻结路径——其自动恢复由既有熔断冷却承载（不递增尝试、冷却期满自动重派）；走 freeze_for_human 的冻结置 frozen=True 后被有意等待豁免命中属「冻结转人工」预期语义。

#### Scenario: 供给瞬态不冻结、冷却自动恢复
- **WHEN** 评审 run 因 api_error_status=429 等供给瞬态失败且被分类为 infra
- **THEN** 不递增 _review_attempts、不产生冻结，infra_breaker 武装冷却，冷却期满 dispatch_review 自动重派

#### Scenario: 评审冻结文案区分且可解冻还原
- **WHEN** 评审器连续失败达尝试上限触发冻结
- **THEN** 冻结文案使用评审专用前缀（与「用户指令冻结」可区分）、含可解析的「原状态 reviewing」、不命中 _INTENTIONAL_PAUSE_MARKERS 且不以 "frozen:" 开头，冻结与告警成对落盘

#### Scenario: 质量冻结语义不变
- **WHEN** 评审质量不达标触发的冻结发生
- **THEN** 冻结行为、告警与解冻还原路径与现状一致