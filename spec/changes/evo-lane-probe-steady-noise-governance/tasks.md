## Deliverables

```yaml
- path: core/agent_runner/lane_preflight.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_lane_preflight_steady_noise.py
  kind: new
```

## 1. 探针稳态边沿发射

- [x] 1.1 core/agent_runner/lane_preflight.py：探针维护上次判定结论（`(ok, fallback_verdicts, reasons 归一集)` 三元可比域）与稳态进入时刻；结论变化（含首判）即时打 WARNING，同判稳态不再逐拍重打，改每小时 1 条携带持续时长的心跳；稳态记忆进程级单例+锁保护、monotonic 时基；判定返回值与回落冻结闸拦截语义零改动。
- [x] 1.2 fenixd.py（_lane_preflight_consume 自检消费点）：改为仅在探针侧边沿/心跳拍发射，消除同拍双组件重复行。

## 2. 告警生命周期对齐

- [x] 2.1 core/agent_runner/lane_preflight.py（告警登记/重武装段）：人工 handled 后同一稳态不重开告警（一次性终态登记），闸收口在 ensure_lane_env_alert 入口、覆盖两个登记调用方（fenixd.py _lane_preflight_consume 的 startup/periodic 与 core/pm_engine/arbiter.py:1972 run infra 失败路径）；判定改变（环境形态变化/试呼裁决翻转）才按新边沿重开；闸不拦截 AdminStore update 定位改写路径（与 evo-repair-lane-credential-probe-fix 1.3 话术翻转共存）；告警正文生命周期承诺与实际行为一致。

> 原 2.2（core/self_review.py 提醒豁免）撤销：「超 24h 未处理」提醒的生命周期方向由已提交的 evo-repair-lane-credential-probe-fix 1.3 单源承接（>24h 升级话术翻转方向），本 SPEC 不与其竞裁、不改 core/self_review.py（Deliverables 已同步移除）。动手前先核对方是否已落盘 lane_preflight.py，后落地方以对方语义为基线合入（design D5）。

## 3. 测试

- [x] 3.1 tests/test_lane_preflight_steady_noise.py：覆盖 首判即时告警/同判稳态静默（含 unhealthy 同判但 reasons/verdicts 漂移须按新边沿发射）/每小时心跳恰一条/结论变化即时告警/恢复边沿播报 五个分支，并断言判定返回值与拦截语义不回归。
- [x] 3.2 tests/test_lane_preflight_steady_noise.py：覆盖 handled 后同稳态经 _lane_preflight_consume 与 arbiter infra 失败路径两登记调用方均不重开、判定变化（形态漂移/env 变化）重开、AdminStore update 改写路径不被闸拦截三个分支。
