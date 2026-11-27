# 能力规格：self-evolution-retention（自进化条目保留清理）

## 概述

自进化台账条目的周期保留清理行为规范：定义哪些条目在清理中保留、哪些被删除，并保证等待人工裁决的条目不因队列外部压力（新条目持续登记）而无声蒸发。

## 需求

### R1 常规保留集

保留集为「created_at 距今不超过 ITEM_RETENTION_DAYS（缺省 7）天」与「created_at 倒序前 ITEM_RETENTION_MIN（缺省 100）名」的并集；保留集之外的条目为清理候选。

### R2 pending 配额保护

status 为 pending 的条目在 R1 之外获得独立配额：按 created_at 倒序额外保留前 ITEM_RETENTION_PENDING_MIN（缺省 20）名。配额内的 pending 条目不进入清理候选；超出配额的最老 pending 条目仍按 R1 规则正常参与淘汰。pending 配额不得为无界（不得无条件豁免全部 pending），以保证人工永不消费时队列仍可有界收缩。

### R3 清理留痕

每次清理执行的日志行必须包含：total（清理前总数）、kept（保留数）、deleted（删除数）与 deleted_pending（删除条目中 status 为 pending 的条数），使 pending 保全效果可审计。

### R4 幂等与安全

清理幂等：同一台账状态重复执行清理结果一致；清理过程中文件读写失败时按既有 fail-open 语义保留现状，不得因清理动作损坏台账。

## 验收标准

1. 构造超配额 pending 的台账（analyzed 条目超 7 天且超前 100 名、pending 25 条）执行清理：pending 至少保留 created_at 最新的 20 条，超配额的 5 条最老 pending 被删除，analyzed 淘汰行为与既有策略一致。
2. pending 少于配额时全部保留。
3. 清理日志含 deleted_pending 计数且数值正确。
4. 既有 prune_items 测试全部通过，行为无回归。