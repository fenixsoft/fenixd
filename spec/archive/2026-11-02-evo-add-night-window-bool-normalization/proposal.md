## Why
守卫夜间静默窗的配置值 .fenix/config.yaml:302 night_quiet_window: false 为非法布尔，解析单源只认字符串 off，导致 code-fix 车道、审查跨窗顺延、admin 唤起避让三个守卫消费点全部静默哑化约 10 天；断连 10-25→10-29 连续五天准点双断，历史撞窗单次损失 136.197 美元（code-review-1792170059 实锚）。消费期非法值 WARNING 已触发 10 天无人处置，证明仅日志 lint 不足。

## What Changes
1. 解析单源把布尔 false 与 off 同义处理（布尔 true 显式拒判为非法），三消费点共享语义。
2. 配置载入期 lint：沿用弃用键一次性 WARNING 既有模式，对非法窗值载入即告警。
3. 审查/admin 车道的静默 fail-open 处补与 code-fix 车道同款告警对等。
4. 窗值停用期间每日一条聚合提醒，防长期悬置无人察觉。

## Impact
- core/code_fix.py、core/admin_monitor.py、core/config.py
- tests/test_code_fix_night_quiet_window.py、tests/test_code_review_night_defer.py 补用例
- 运维配套（非本 spec）：手工把 config.yaml:302 改为覆盖双断点的合法多窗