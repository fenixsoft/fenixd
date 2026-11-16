## Why

2026-11-12 web-browser-client：验证环境 01:07 根治（0a30212）并探针实证，处置链 17:09:02Z 成功闭环（unfrozen=False）后无任何组件接续迁移——空等 56.74 分钟（blocked 总滞留 80.6 分钟），多烧 1 个 distress 信号（fenixd.log:10606）与 1 个本可避免的 admin run（1038.43s/166 轮/约 14.7 万 tokens，fenixd.log:10636-10638）；同 run 的 manual_fixed_reverify 又因作用域未注册被拒。同族形态 11-09 在 single-app-realdevice-retest 已两度出现（unfreeze/reset→testing 不入队 verifier、处置回执缺下游落地校验），跨日第三例。

## What

1. 环境阻塞族信号的处置闭环自动接续既有复位直通道（blocked→testing + 入队 verifier），互斥跳过登记待重评并周期消费。
2. 处置回执写可核验句柄并做落地校验，未落地告警并标记处置无效。
3. blocked_stuck 补裁决选项桶与白名单，提示词词表按信号桶收窄。

## Goals

环境修复后的重验恢复不再依赖 stuck 超时兜底；处置「成功」语义以可核验落地为唯一依据。