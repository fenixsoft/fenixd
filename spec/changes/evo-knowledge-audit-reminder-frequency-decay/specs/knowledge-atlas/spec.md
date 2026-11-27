# 能力：知识体检聚合提醒降频（knowledge-atlas）

## Requirement: 超期未消费提醒降频

escalated 聚合提醒在持续零仲裁消费超过阈值天数（缺省 7 天，与 disputed 注记 stale_days 语义对齐）后，MUST 降频为每周一拍：距最近一次提醒落库不足 7 天时不再改写 todo 聚合行，提醒文案注明「已降频为每周一拍、欠账仍在」。

## Requirement: 消费后节拍恢复

任一 escalated 指纹被仲裁消费（consume_arbitration 命中）后，MUST 恢复每日节拍直至剩余疑点再次满足降频条件；全部消费后提醒按既有语义止拍。

## Requirement: 欠账信号不丢失

降频期间 MUST NOT 影响：disputed 注记写入（core/knowledge_audit.py 既有 stale_days 逻辑）、todo 聚合行的存在性与原位替换语义、消费检查点行为。

## Scenario: 超 7 天未消费降频

- WHEN escalated 聚合提醒连续超 7 天零消费
- THEN 提醒改为每 7 天一拍，文案含降频注记，disputed 注记不变

## Scenario: 部分消费后恢复每日节拍

- WHEN 降频期间任一指纹被仲裁消费
- THEN 提醒恢复每日节拍，按剩余疑点重新计数

## Scenario: 全部消费后止拍

- WHEN 13 条 escalated 全部被消费
- THEN 聚合提醒按既有语义不再落库