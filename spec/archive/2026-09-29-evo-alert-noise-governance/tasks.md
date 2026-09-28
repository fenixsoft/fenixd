## Deliverables

```yaml
- path: core/pm_engine/spec_integrity.py
  kind: modify
- path: core/alert_lifecycle.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: core/dashboard/registry.py
  kind: reference
- path: tests/test_spec_content_integrity.py
  kind: modify
- path: tests/test_admin_dispatch_escalation.py
  kind: modify
- path: tests/test_fixture_project_governance.py
  kind: modify
- path: tests/test_daily_self_review.py
  kind: modify
```

core/dashboard/registry.py 为 fixture:true 标记的权威读取源（fix-fixture-project-alert-noise 落地），本变更只读不改，故声明 reference。tests/test_spec_content_integrity.py 是闸门语义与夹具回归宿主、tests/test_admin_dispatch_escalation.py 是 daemon_errors 升级用例宿主，均已在主树存在故声明 modify。

## 1. 闸门分类修正（源头）

- [x] 1.1 core/pm_engine/spec_integrity.py：check_spec_content_missing 入口对终态（done/archived）短路——不冻结、不出 spec_content_missing（与既有 status==blocked 幂等短路并列，状态以 STATE.md 当前值为准），并注释固化「终态豁免不等于放行派发」。
- [x] 1.2 core/pm_engine/spec_integrity.py：命中空判定且目录存在 verification-report.md 时，改产 spec_delivered_no_content 信号（新常量），不冻结，文案引导人工裁决（补 tasks.md 归档凭据或明确废弃）；无验证报告时维持既有 spec_content_missing + 冻结路径。该分支 MUST 自带幂等短路——不冻结则状态不变，闸门会随恢复精触发（60s）与 full_scan 反复命中，重复命中时若已存在同 spec 同 signal_type 未处理告警 MUST NOT 追加新记录（对齐 admin_monitor._throttled 的「已存在未处理升级告警」判据），防止每分钟一条 major 告警风暴。
- [x] 1.3 core/pm_engine/spec_integrity.py：spec_has_content 四选一判据不动——verification-report.md MUST NOT 进入认可名单，注释固化理由（防止 STATE 被外部重置的已交付 spec 被盲目重派，09-12 实证事故）。
- [x] 1.4 core/alert_lifecycle.py：注册独立闭环条件 spec_delivered_adjudicated（新常量）并加入 _SIGNAL_CONDITIONS；evaluate_alert 为其新增判定分支——仅当关联 SPEC 到达终态（done/archived）才闭环，非终态（含 ready/blocked）保持原状。MUST NOT 复用 CONDITION_SPEC_TERMINAL_OR_UNBLOCKED：该条件在 evaluate_alert 中仅以 blocked 为未解除出口（alert_lifecycle.py:135-138），本信号产生时 SPEC 停在 ready 待裁决，复用会使告警被下一轮 auto_resolve 立即闭环、人工无从看见。

## 2. 恢复路径与派发链 frozen 复核（断重放）

- [x] 2.1 core/event_bus.py：_recover_ready 在读 entry 后、清 error 前加 frozen 早退（True 即 INFO 跳过，含 spec 名与原因），并同步 recover_orphan_ready docstring 早退清单；保持早退路径零 STATE 写入。
- [x] 2.2 core/pm_engine/engine.py：_on_spec_ready 守卫链中加入 frozen 检查（read_one 之后、闸门内容校验之前），命中即 INFO 跳过派发；可复用 _frozen_state 助手保持 legacy 文本契约兼容。
- [x] 2.3 两处复核均 MUST NOT 改变非冻结 spec 的既有行为（恢复流程、派发守卫顺序与语义回归）。

## 3. daemon_errors 升级冷却与孪生合并（降敏）

- [x] 3.1 core/admin_monitor.py：_detect_daemon_errors 增加指纹级冷却——记录指纹上次唤起时间戳，daemon 启动后冷却窗内已知指纹不计满升级阈值、不召唤（INFO 留痕冷却决策）；冷却常量与 DAEMON_ERROR_THRESHOLD 同层声明，不新增配置键。「已知指纹」识别 MUST 覆盖跨重启场景（治理目标正是重启后首扫回放）：生命周期内用内存时间戳，跨重启对账 admin store 既有 daemon_errors 告警——store 记录无结构化指纹字段（_fp 仅内存传递不落库，admin_monitor.py:1728-1731），须以 description 内嵌指纹前缀文本对账，或为 daemon_errors 告警 entry 增补结构化指纹字段，二者任务内定其一。
- [x] 3.2 core/admin_monitor.py：同轮扫描的孪生/成对指纹按 fp 聚合合并为一条召唤信号（一次 Administrator run）。
- [x] 3.3 core/admin_monitor.py：冷却仅约束重启后首扫窗口，窗后复现或全新指纹照常升级；与既有 _throttled 节流的关系在注释中说明（补口而非替代）。

## 4. 日审读侧过滤（消费端 ①）

- [x] 4.1 core/self_review.py：_collect_admin_summary 装配前识别项目 fixture 标记（复用 core/dashboard/registry.py 既有读取入口，依赖方向不允许时经配置层注入）；标记项目的告警不计入未处理计数，摘要以 fixture 标注单独呈现，不与真实告警混排；MUST NOT 删除或改写告警记录。
- [x] 4.2 core/self_review.py：无 fixture 标记（或标记读取失败）的项目行为保持现状（fail-open 到现状，计数口径与摘要结构不变）。

## 5. 召唤通道 fixture 抑制（消费端 ②）

- [x] 5.1 core/admin_monitor.py：distress 升级召唤决策点查项目 fixture 标记，命中则记 INFO（含错误指纹与抑制原因）并跳过自动召唤（含全局巡检类 admin-global run）；人工显式触发通道不受限。抑制判定 MUST 置于各自动检测路径调用 _invoke_administrator 之前（自动调用点 admin_monitor.py:1352/1908/2085/2332 一带），MUST NOT 放进 _invoke_administrator 本体——人工显式触发（run_administrator）与自动检测共用该入口（admin_monitor.py:2539 注释），放本体必误伤人工通道。
- [x] 5.2 core/admin_monitor.py：抑制决策 MUST NOT 修改/删除告警记录本身（看板仍可见），仅阻断召唤动作。

## 6. 测试

- [x] 6.1 tests/test_spec_content_integrity.py：覆盖终态豁免（done 态空目录不冻结不告警、状态保持 done）、仅含 verification-report.md 出 spec_delivered_no_content 且不冻结、无验证报告仍走既有冻结路径（语义回归）、spec_has_content 对仅验证报告目录仍判无内容、spec_delivered_no_content 经生命周期条件自动闭环（补内容与置终态两路径）。
- [x] 6.2 tests/test_spec_content_integrity.py：覆盖冻结 spec 被外部置回 ready 后——孤儿恢复跳过（零 STATE 写入、INFO 留痕）、重启回放经 _on_spec_ready 跳过派发不再产生闸门 ERROR；非冻结 spec 恢复/派发行为回归。
- [x] 6.3 tests/test_admin_dispatch_escalation.py：覆盖升级冷却（重启后首扫已知指纹不召唤、留痕）与孪生指纹合并（成对命中只产一条信号），以及冷却窗后复现照常升级。
- [x] 6.4 tests/test_fixture_project_governance.py：覆盖召唤抑制（fixture 项目达升级条件不建 admin-global run 且留 INFO 痕、人工触发不受限、告警记录不被改动、非 fixture 项目照常召唤）。
- [x] 6.5 tests/test_daily_self_review.py：覆盖日审摘要过滤（fixture 告警不进未处理计数且带标注、非 fixture 项目计数与结构不变、标记读取失败时 fail-open）。
