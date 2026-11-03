# 争议冻结升级与并行唤起 admin 处置的互斥竞态

## Why

本例争议满 2 轮转人工时框架将 spec 置 frozen=True，同刻并行唤起的两个 admin run 一个被 frozen-terminated 秒败（error: run frozen-terminated by admin: spec frozen）、一个 15 分钟孤儿超时——升级转人工的冻结语义与同窗 admin 自动处置通道自相矛盾，冗余唤起白白消耗预算且放大处置假死时长（本例两 run 全数零效果后空转至 Arbiter 触发）。建议：转人工升级唤起 admin 时豁免冻结闸或升级时不再并行唤起 admin（二选一收口），冻结仅用于阻止 verify 派发而非阻止处置。

## What Changes

- （arbiter 提案待人工成文：本文件为调查报告提案的最小诚实成文，补全 What Changes / Capabilities / Impact 后走既有晋升流程）

## Capabilities

### New Capabilities

- `<capability>`: （待成文）

### Modified Capabilities

（无）

## Impact

（待成文）

---

- 立项来源：Arbiter 调查（run_id=None，signature=add-knowledge-inbox-pipeline::verify_env_blocked，source=startup）
- 立项时间：2026-11-03T13:25:51.838217+00:00
