## Why

2026-11-11（UTC）cloud-phone 实例 web-browser-client：验证环境 01:07（+0800，即 UTC 11-11 17:07）根治（0a30212）并探针实证，处置链 17:09:02Z 成功闭环（unfrozen=False）后无任何组件接续迁移——空等 56.74 分钟（blocked 总滞留 80.6 分钟），多烧 1 个 distress 信号与 1 个本可避免的 admin run（admin-web-browser-client-1794419307，1038.43s/166 轮/约 14.7 万 tokens）；同 run 的 manual_fixed_reverify 又因作用域未注册被拒（scoped-no-reverse）。以上事件证据均在 cloud-phone 实例日志 /root/cloud-phone/.fenix/logs/fenixd.log:10571/10582/10606/10636-10641 逐条在案（fenixd 框架仓本仓日志同行号为无关内容，引用日志行号须注明实例归属）。同族形态 11-09 在 single-app-realdevice-retest 已两度出现（unfreeze/reset→testing 不入队 verifier、处置回执缺下游落地校验，同日志 10:16:16Z 复位互斥跳过在案），跨日第三例。

## What

1. 环境阻塞族信号的处置闭环自动接续既有复位直通道（blocked→testing + 入队 verifier），互斥跳过登记待重评并周期消费。
2. 处置回执写可核验句柄并做落地校验，未落地告警并标记处置无效。
3. blocked_stuck 补裁决选项桶与白名单，提示词词表按信号桶收窄。

## Goals

环境修复后的重验恢复不再依赖 stuck 超时兜底；处置「成功」语义以可核验落地为唯一依据。