# 验证报告：add-adjudication-auto-exec

> ⚠️ 本报告由框架于 2026-11-11T05:04:47Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-11T05:04:47.352921+00:00+run-result@mtime1794373487398084770

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 16.21M |
| 本链增量 Token（输出） | 0.20M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| seed-fixture-autoexec-demo-records | 夹具演示件种子：向验证夹具项目 scheduling-showcase 的告警存储幂等种入两条链终点形态演示告警——①autoexec-demo-pending（pending、reversible 推荐落账 5 分钟、grace 窗内）②autoexec-demo-executed（handled_by=auto-policy、已收口）及一条 actor=auto-policy 处置留痕，供 api/web 依赖场景读取展示（demo id 固定、重复执行先清后种）。已注册夹具（fixture=True），零注册表写动作。 | pass | 0/4 | - |
| risk-tier-registry-declared | 裁决选项风险档位声明（specs/adjudication-choices-registry）：注册表每个 choice 条目携带合法 risk_tier（三档枚举），judge_rerun_cap 桶 manual_fixed_reverify=reversible-experiment、force_advance=state-advance、abandon=terminal；同 id 跨桶档位一致；choices_for 快照拷贝透出档位；既有 resolve_choice 解析行为零回归（action/destructive/not-in-bucket 形态）。 | pass | 0/7 | - |
| auto-exec-config-defaults-single-source | auto_exec 配置单源（tasks 1.1）：core/config.py 以签名常量声明 enabled=True、grace_minutes=30、consecutive_max=2、aging_warning_minutes=120、aging_critical_minutes=360 缺省（AUTO_EXEC_* 命名族）。 | pass | 0/7 | - |
| auto-exec-executes-reversible-after-grace | 可逆推荐到点自动执行（specs/adjudication-auto-exec 场景「到点自动执行可逆推荐」）：tmp 项目根种一条 judge_rerun_cap 升级告警（arbiter 完整调查落账 31 分钟前、推荐 manual_fixed_reverify 文本正向提及唯一、reversible-experiment 档、无共存更高档、连续计数 0），驱动策略引擎单轮扫描——告警转已处理、处置留痕 actor=auto-policy 且 choice_id=manual_fixed_reverify（与人工同构，OR 兼容 handled_by=auto-policy 形态）、执行触达状态机（reset_verification 落盘证据：状态解冻/推进或调度唤醒信号）。 | pass | 0/7 | - |
| auto-exec-criteria-skips-logged | 判据缺失逐条跳过（specs/adjudication-auto-exec 场景「判据缺失跳过」「推荐歧义跳过」「异步升级件否决窗完整」+ 判据③共存更高档）：六个 tmp 根分别覆盖——推荐 terminal 档（abandon 正向）、推荐歧义（两 id 正向提及）、零正向命中、无 arbiter_upgrade 痕、grace 窗未满（落账 8 分钟）、同 spec 共存更高档 pending——每例驱动单轮扫描后告警 MUST 维持 pending，不部分执行。 | pass | 0/8 | - |
| auto-exec-cap-human-first-switch-isolation | 连续上限/人工先到/开关降级/异常隔离（specs/adjudication-auto-exec「人工先到先得」「连续超限强制人工」「开关降级与异常隔离」）：同一根内人工已 mark_handled 后引擎不再自动处置且零 actor=auto-policy 新留痕；同 spec 两条连续自动执行成功后第三条转 pending 等人工（cap=2）；auto_exec.enabled=false（项目级 config.yaml+注入双形态）时整体停用保持 pending；坏 upgraded_at 告警判定异常不炸本轮、同轮好告警照常执行。 | pass | 0/10 | - |
| auto-exec-aging-visibility-human-only | human-only 档老化升级（specs/adjudication-auto-exec「不可逆档持续可见不自动动」+ tasks 2.3）：推荐 force_advance（state-advance 档）的 pending 告警超 2h/6h 老化阈值时引擎不执行、写升级活动记录（宽网探测：新增/改写的 .fenix 文件或新增存储记录提及告警 id），未超阈值的同档新告警不写老化记录。 | pass | 0/7 | - |
| event-bus-testing-instant-dispatch | 外部 testing 跃迁即时派发（specs/testing-dispatch-liveness）：进程内装配 EventBus（假 StateMachine/PMEngine，锁内重读口径），blocked→testing 无驱动跃迁 MUST 立即触发 verifier 派发（变更前 testing 无事件映射＝零派发，恰红收口类）；有驱动（近期 run 文件）与在飞 Administrator run（agent_runner 伪 running_run_ids）两回归锚不重复派发；派发调用失败被吸收不外溢、快照推进不受损、30min full_scan 兜底语义共存（attempt 在场即证据）。出处 core/event_bus.py:1301 _dispatch_changes、:623 _recover_testing。 | pass | 0/8 | - |
| daemon-assembly-auto-exec-wiring | daemon 装配与复用纪律（tasks 3.1/2.2 + design 决策 3）：core/admin_auto_exec.py 存在且被 fenixd.py 引用装配；引擎源复用 execute_choice_for_disposition 单机器（禁第四份复制）、携带 actor=auto-policy 留痕形态字面量、读 auto_exec 配置键、含 reversible-experiment 档位门、具周期扫描形态（sleep/Timer/threading/interval 任一）。 | pass | 0/9 | - |
| deliverable-test-suites-green | 本 SPEC 新增交付测试套件全绿（tasks 1.3/2.4/4.2/5.3）：pytest 运行三个新测试文件（risk_tier/auto_exec 策略/event_bus testing 派发）断言 exit 0 且存在 PASSED 行、无 FAILED；node --test 运行前端 autoExecBadge.test.mjs（徽标渲染与 grace 倒计时逻辑）断言 exit 0 且 fail 0（node21+ reporter 形态实测校准）。与回归锚场景共享 resource_group 串行防 pytest 并发互扰。 | pass | 0/4 | - |
| existing-suites-regression-anchor | 既有套件回归锚（specs/adjudication-choices-registry「档位不改变既有行为」+ 链序不变承诺）：risk_tier 注入后既有裁决注册表/事件总线/升级链三套件通过数维持实测基线（62/38/59，变更前树实测校准；计数锚防空洞绿灯，套件缩水或行为回归即红）。与新增套件场景共享 resource_group 串行。 | pass | 0/6 | - |
| api-alerts-autoexec-fields | 告警读取层透出自动执行字段（tasks 5.1）：GET /api/alerts?project=scheduling-showcase（点名分支含夹具）——auto-executed 演示件记录 handled_by=auto-policy 在场（徽标派生数据源）、pending 演示件 choices 快照首项携带 risk_tier=reversible-experiment（档位经注册表→发射快照→HTTP 面可达，供倒计时/徽标前端派生）。出处 core/dashboard/routes/base.py:632、core/dashboard/routes/alert_routes.py:120-151。 | pass | 0/7 | - |
| api-chain-escalations-autoexec-view | 处置链视图呈现演示件（ChainPanel 数据面，tasks 5.2 前置）：GET /api/chain?project=scheduling-showcase——escalations 全量段含已收口演示件（handled=true 且 handled_by=auto-policy 行级在场）与 pending 演示件；queue 段仅收 pending 演示件（人工队列口径）。出处 core/dashboard/routes/base.py:635、core/dashboard/routes/alert_routes.py:193-222、core/dashboard/data/admin_alerts.py:311 chain_overview。 | pass | 0/7 | - |
| web-chain-panel-autoexec-badge | 运维页处置链徽标展示（tasks 5.2）：导航 /#/activities（处置链页签缺省激活），标题栏筛选 Select 选 scheduling-showcase 后——pending 演示件行与已收口演示件行均渲染；自动执行记录以独立「自动执行」徽标可见（非静默混入人工；徽标文案锚取 SPEC 用语 auto-executed 的中文呈现「自动执行」，grace 倒计时逻辑由 autoExecBadge.test.mjs 单测承担）。出处 core/dashboard/static/src/app.tsx:158（/activities SPA 路由）、activities/index.tsx:294-298（chain 缺省页签）、:903-914（标题栏筛选槽 Select）、ChainPanel.tsx:964-997（上升件行卡）。 | pass | 0/5 | - |
| web-chain-panel-aggregate-excludes-fixture | 夹具告警不泄漏人工聚合视图（fixture-project-governance 回归锚，ADR-163）：默认聚合分支（不选项目）下处置链上升件 MUST NOT 出现夹具演示件行——验证夹具对照告警被跨项目聚合过滤降噪、不引发人工误排查。出处 core/dashboard/routes/alert_routes.py:102-114（_aggregatable_projects 跳过 fixture）、activities/index.tsx:903-914（缺省全部项目）。 | pass | 0/4 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

