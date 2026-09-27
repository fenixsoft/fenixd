<!-- knowledge: capability=manual-invoke-signal-passthrough rev=1 sources=spec/archive/2026-09-27-fix-manual-invoke-signal-type-passthrough -->

# 手动唤起信号底层类型透传

手动唤起 Administrator 时把底层触发信号的类型随处置信号透传，使处置收尾自动复位判定门对手动通道同样生效。

## 现行规则

- daemon 消费 `.fenix/admin_invoke_request.json` 构造处置信号时，反查该 spec 最近一条未处置（非 handled）的 SIGNAL/ESCALATION 记录（按 created 取最新，排除 `signal_type == "manual-intervention"` 的手动通道自产记录），取其 `signal_type` 写入信号的 `underlying_signal_type` 字段；查不到时该字段为 None。
- 信号顶层 `signal_type` 保持 `manual-intervention`：store 记录、节流锚点、admin 活动区展示语义不变；透传字段不参与节流、不产生重复告警。
- 处置收尾自动复位判定门按「或」命中：`signal_type` 或 `underlying_signal_type` 任一命中 `DISPOSITION_AUTO_RESET_SIGNAL_TYPES`（env 阻塞族 + blocked_stuck）即触发自动复位——实现分支已合并走 testing 直通道重验，否则回 ready，spec 不悬置 blocked。
- 其余复位语义不变：`escalated` 不复位；复位守卫（frozen / 非 blocked）不放松；业务侧车字段不清零；底层类型不在复位集合（如 orphaned_state）时走其既有独立复位路径，不触发本门。
- 无可反查信号时唤起流程不报错：`underlying_signal_type` 为 None、顶层仍为 `manual-intervention`，处置照常执行。

## 溯源

- 2026-09-27 fix-manual-invoke-signal-type-passthrough — 落地底层 signal_type 反查透传与自动复位判定门「或」命中扩展，顶层类型保持 manual-intervention 保证 store/节流/展示零回归
