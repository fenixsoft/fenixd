## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/admin_auto_exec.py
  kind: new
- path: core/admin_choice_exec.py
  kind: modify
- path: core/dashboard/data/admin_alerts.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/static/src/pages/activities/components/ChainPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: tests/test_adjudication_choices_risk_tier.py
  kind: new
- path: tests/test_admin_auto_exec_policy.py
  kind: new
- path: tests/test_event_bus_testing_dispatch.py
  kind: new
- path: core/dashboard/static/tests/autoExecBadge.test.mjs
  kind: new
- path: spec/knowledge/domains/admin-ops/adjudication-choices-registry.md
  kind: modify
- path: spec/knowledge/domains/admin-ops/escalation-chain.md
  kind: modify
```

## 1. 配置单源与注册表风险档位

- [ ] 1.1 core/config.py 新增 auto_exec 配置单源：enabled（缺省 true）、grace_minutes（缺省 30）、consecutive_max（缺省 2）、aging_warning_minutes/aging_critical_minutes（缺省 120/360），签名常量形态与既有配置键风格一致
- [ ] 1.2 core/dashboard/data/adjudication_choices.py 为全部 choice 条目声明 risk_tier（judge_rerun_cap 桶：manual_fixed_reverify=reversible-experiment、force_advance=state-advance、abandon=terminal；其余桶按动作不可逆性定档），缺档读取侧按 terminal 兜底，不改变既有解析/payload/执行行为
- [ ] 1.3 新增 tests/test_adjudication_choices_risk_tier.py：覆盖每条选项档位合法、缺档 terminal 兜底、既有 resolve_choice 行为不回归

## 2. 自动执行策略引擎

- [x] 2.1 新增 core/admin_auto_exec.py 扫描判定：60s 轮询读 pending 升级告警，判据四条全过才到点执行（arbiter 完整调查≥1 且有明确推荐 choice——由告警 choices[] 注册 id 对 recommended_action 文本正向提及解析，否定语境不计，唯一命中方执行、零/多义命中跳过；推荐 choice risk_tier=reversible-experiment、同 SPEC 无共存更高档 pending、连续 auto-exec 计数<cap——计数从处置留痕按 actor=auto-policy 派生不新增状态文件），grace 到期时刻=推荐可用时刻（arbiter_upgrade.upgraded_at，无 upgrade 痕回退 created）+grace_minutes 读时计算，任一判据不满足跳过并记日志
- [x] 2.2 同模块实现到点执行：执行前瞬时重读 handled 与判据（人工先到先得），复用 core/admin_choice_exec.py 单机器执行（如需扩 actor=auto-policy 留痕形态则修改该模块），留痕与人工同构，异常单条捕获隔离、enabled=false 时整体停用
- [x] 2.3 human-only 档老化升级：pending 超 aging 阈值（2h/6h 两档）的 state-advance/terminal 告警写升级活动记录（复用既有活动记录写入点），只做可见性不执行动作
- [x] 2.4 新增 tests/test_admin_auto_exec_policy.py：覆盖到点自动执行成功留痕 actor=auto-policy、四判据逐条缺失跳过（含推荐歧义/零命中跳过）、grace 自推荐落账时刻起算（异步升级件 upgraded_at 晚于 created 时窗口完整）、人工先到先得不重复执行、连续 cap 超限转人工、开关停用、异常单条隔离

## 3. daemon 装配

- [x] 3.1 fenixd.py 在 admin 告警通道装配区（EventBus 初始化附近，~:788）实例化策略引擎并启动 60s 扫描环，注入 logger 与既有依赖引用，disabled/异常降级不影响其他车道启动

## 4. 外部 testing 跃迁即时派发

- [ ] 4.1 core/event_bus.py 的 _dispatch_changes 增加 →testing 跃迁处理：spec_is_undriven 命中且无在飞 Administrator run（复用 _recover_testing 与 _spec_has_active_admin_run 既有语义）时立即 re-trigger verifier 派发，不新增事件类型，失败不留状态损坏；锁纪律：`_dispatch_changes` 既有约定 PM Engine 处理必须在 `_state_lock` 外执行（docstring 明文），锁内只采集 →testing 跃迁、re-trigger 派发放锁外
- [ ] 4.2 新增 tests/test_event_bus_testing_dispatch.py：覆盖 blocked→testing 秒级触发派发、有驱动/在飞 run 不重复派发、派发失败语义与 30min full_scan 兜底共存

## 5. Dashboard 展示

- [ ] 5.1 core/dashboard/data/admin_alerts.py 读时合并层透出自动执行所需字段：handled_by=auto-policy 值、created_at、推荐 choice 与 risk_tier（供倒计时与徽标派生，无 schema 变更）
- [ ] 5.2 ChainPanel.tsx + services/dashboard.ts：自动执行记录独立徽标展示（非静默混入人工），满足条件的 pending 告警展示 grace 倒计时标注
- [ ] 5.3 新增 core/dashboard/static/tests/autoExecBadge.test.mjs：覆盖徽标渲染与倒计时展示逻辑

## 6. 知识页同步

- [ ] 6.1 更新 spec/knowledge/domains/admin-ops/adjudication-choices-registry.md（risk_tier 三档与兜底语义）与 spec/knowledge/domains/admin-ops/escalation-chain.md（链终点 auto-exec 语义、判据、cap、开关），rev 递增与既有格式一致
