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

### Requirement: 冻结前缀区分供给瞬态与质量不达标
评审冻结 SHALL 按根因区分前缀（供给瞬态 vs 评审质量不达标）；供给瞬态前缀 SHALL NOT 命中 _INTENTIONAL_PAUSE_MARKERS（避免被误判为有意等待而压制自动唤起），且 SHALL 保留「原状态 reviewing」子串供 parse_orig_status 解冻还原、SHALL 仍经 freeze_for_human 成对入口落冻结与告警。

#### Scenario: 瞬态冻结可自动恢复
- **WHEN** 供给瞬态类冻结发生
- **THEN** 该 spec 不被 intentionally-paused 豁免跳过自动唤起，冻结文案含可解析的「原状态 reviewing」

#### Scenario: 质量冻结语义不变
- **WHEN** 评审质量不达标触发的冻结发生
- **THEN** 冻结行为、告警与解冻还原路径与现状一致