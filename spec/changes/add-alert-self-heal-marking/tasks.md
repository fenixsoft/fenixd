## Deliverables

```yaml
- path: core/alert_lifecycle.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/config.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/data/admin_alerts.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SystemPanel.tsx
  kind: modify
- path: core/dashboard/static/src/components/alert-shared.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_alert_self_heal.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 评估器扩展（纯函数）

- [ ] 1.1 `core/alert_lifecycle.py` 新增常量与判定：`CONDITION_INFRA_TRANSIENT_SELF_HEALED`、`SELF_HEAL_SIGNAL_TYPES`（daemon_errors / run_infra_failure / evo 分析失败 signal_type，写入点常量核对后登记）、安静时刻解析（条目 `last_seen` 回落 `created`；收敛升级按 `admin_run_id` 关联名下条目取最新）
- [ ] 1.2 `core/alert_lifecycle.py` `evaluate_alert` 扩展：spec-less 条目（spec 为空）＋`kind ∈ {signal, escalation}` 走自愈分支——签名安静 ≥ 窗口分钟返回「已自愈：…」note（含安静时长与最近复现时刻）；未注册 signal_type / 形态不符 / 窗口内复现 / `handled=True` 一律 None；`build_trigger`/`_SIGNAL_CONDITIONS` 登记新族使既有 `attach_trigger` 写入点自动埋点
- [ ] 1.3 存量回填：无 trigger 的 spec-less 条目按 `signal_type ∈ SELF_HEAL_SIGNAL_TYPES` 推断（与既有 `BACKFILL_SIGNAL_TYPES` 机制并列，note 注明存量回填）
- [ ] 1.4 `tests/test_alert_self_heal.py`：安静超窗闭环 / 窗口内复现保持 / env 握手族排除 / spec 附着族不双重判定 / handled 不覆盖 / 回填推断六组用例

## 2. 存储写回

- [ ] 2.1 `core/admin_store.py` 新增 `auto_self_heal(resolutions)`：可关闭 `kind ∈ {escalation, signal}` 未 handled 条目，`handled_by="auto-self-heal"`、`handled_at`、`resolve_note`；排他锁单次读-改-写、零写回 mtime 不变、MUST NOT 触碰 disposition 记录本体（对齐既有 `auto_resolve` 实现模式）
- [ ] 2.2 `tests/test_alert_self_heal.py`：signal 族与 escalation 族写回 / handled 跳过 / disposition result 字段逐位不变 / 空解析零写回四组用例

## 3. 巡检接线

- [ ] 3.1 `core/admin_monitor.py` `_run_alert_lifecycle` 扩展双通道：既有 spec 附着判定不变；新通道把全量告警（含 spec-less）与当前时刻注入自愈判定，产出 resolutions 经 `AdminStore.auto_self_heal` 写回；逐段 try 兜底不阻断巡检（对齐同函数既有风格）
- [ ] 3.2 `core/config.py` `get_admin_config` 新增 `self_heal_quiet_minutes`（缺省 1440；负数/零/非 int/bool 回退缺省）；`tests/test_alert_self_heal.py` 补配置兜底用例

## 4. 写侧埋点补全

- [ ] 4.1 `core/admin_monitor.py`：核对 daemon_errors 升级、run_infra_failure 熔断、收敛升级三处写入点均已过 `attach_trigger`（既有统一埋点），补缺失处并保证 signal 条目 `last_seen` 复现刷新逻辑不被本变更破坏
- [ ] 4.2 `fenixd.py` `_evolution_warn` 写入点：条目接入 `attach_trigger` 埋点（signal_type 与 `SELF_HEAL_SIGNAL_TYPES` 登记值一致）；`tests/test_alert_self_heal.py` 补埋点断言

## 5. 配置与 Dashboard

- [ ] 5.1 `.fenix/config.template.yaml` admin 段补 `self_heal_quiet_minutes` 注释条目（默认 1440、语义「瞬态告警签名安静多久后标已自愈」）
- [ ] 5.2 `core/dashboard/data/config_admin.py` 透出该字段读写（非法值拒绝并报错）；`SystemPanel.tsx` 增「告警自愈安静窗口（分钟）」数字输入，走既有面板脏检查与提交链路
- [ ] 5.3 `core/dashboard/data/admin_alerts.py` 透出 `handled_by`；`alert-shared.tsx` 徽标映射 `auto-self-heal → 已自愈`（区别既有 auto-resolve 文案）；`services/dashboard.ts` 类型补字段；`tests/test_alert_self_heal.py` 补数据层映射断言
