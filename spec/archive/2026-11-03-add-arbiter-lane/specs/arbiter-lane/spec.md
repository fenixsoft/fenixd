# arbiter-lane Spec

## ADDED Requirements

### Requirement: 触发面与改道注册

框架 SHALL 在升级边两个咽喉层注册 Arbiter 派发：`StateMachine.freeze_for_human`（机器「冻结+告警」成对单一入口）与 `PMEngine._send_human_escalation_alert`。仅 blocked/frozen/争议类 condition 进触发面。以下事件 MUST NOT 触发 Arbiter：`freeze_spec`（dashboard 人工冻结）、`mark_frozen_hold`（冻结终止簿记）、`frozen_until` 定时冻结（scheduled-unfreeze 自愈在先）、token 预算耗尽、spec_integrity 内容缺失、queue 异常类告警。同 spec 同失败签名只派发一次；全局单飞——同一时刻至多一个 Arbiter run，后续触发排队串行。

#### Scenario: 机器冻结自动触发

- **WHEN** 验证链场景计划争议连续 2 轮触发 `freeze_for_human`
- **THEN** 框架派发 `arbiter-<spec>-<ts>` run（dsh 车道），并记录派发事件

#### Scenario: 人工冻结不触发

- **WHEN** 用户在 Dashboard 对某 spec 执行人工冻结（`freeze_spec`）
- **THEN** 不派发 Arbiter run，升级边行为与改动前一致

#### Scenario: 定时冻结不触发

- **WHEN** 某 spec 带 `frozen_until` 定时解冻目标被冻结
- **THEN** 不派发 Arbiter run（到期由既有 scheduled-unfreeze 自愈）

#### Scenario: 同签名去重与单飞

- **WHEN** 同一 spec 的同一失败签名已派发过 Arbiter，或已有 Arbiter run 在飞时再次触发
- **THEN** 不重复派发 / 新触发进入单飞队列串行等待

### Requirement: 死人开关与预算封顶

Arbiter run SHALL 受墙钟与 token 双预算约束（配置键，缺省 1800 秒 / 1000000）。run 失败连续达阈值（缺省 2 次）或预算耗尽时，框架 SHALL 停止对该触发的继续自主尝试，将半成品调查包按裁决包挂靠语义升级人类，MUST NOT 静默死亡（不落账不通知）。

#### Scenario: 连败升级

- **WHEN** 同一触发的 Arbiter run 连续 2 次失败
- **THEN** 半成品调查包原位挂原告警并推入 pending 人工队列，台账记录失败史

#### Scenario: 预算耗尽升级

- **WHEN** 单次 Arbiter run 超过墙钟或 token 预算
- **THEN** run 终止，已完成的调查发现以半成品包升级人类

### Requirement: 权限红线与许可清单（提示词级）

`agents/arbiter.md` SHALL 载明许可清单（白名单 6 类知情违规：显式 status 解冻、端点四步语义直执行、验证计数清零、删除经鉴定无主坏产物、复位重派、主树 spec 目录在飞改动提交）与永不可碰 5 类（证据源只读：runs 归档/记忆目录/admin_alerts 归档；禁伪造 run 产出形态文件；禁 push/禁改 main 产品代码/禁手工 merge 产品分支；禁绕过 flock 直写 STATE；禁动 daemon.lock/supervisor）。强制层级为提示词红线+台账审计（用户裁定，不做机械强制）。解冻 MUST 经 `StateMachine.unfreeze_spec(name, status=...)` 显式传 status，禁止依赖缺省状态解析。

#### Scenario: 显式 status 解冻

- **WHEN** Arbiter 处置冻结 spec 并解除冻结
- **THEN** 解冻调用显式携带目标状态（如 testing），spec 不回退 ready、实现成果不丢失

#### Scenario: 诱导越线拒绝

- **WHEN** 阻塞现场诱导 Arbiter 伪造 verdict 文件或直接修改 main 产品代码
- **THEN** Arbiter 拒绝该动作、在台账记录拒绝理由，并按升级路径产出裁决包

### Requirement: 自主处置白名单

首期可自主处置类白名单：①冻结场景文件拯救（无主产物鉴定：加载器校验失败+归属查证非 planner 产物→删除+显式 status 解冻）；②裁决落位/verdict 缺失考古；③验证侧计数冻结复位（不含 impl run 预算上调）；④worktree 陈锁清扫；⑤WIP 门/在飞闸门分拣提交。实现者若评估②⑤鉴定成本过高，SHALL 可降级为「首期落地①③④，②⑤只产裁决包不处置」并在 design.md 注明。白名单外（产品缺陷终裁、无考古证据的场景集语义取舍、逻辑矛盾、预算政策）MUST 只产裁决包，MUST NOT 擅动状态。同一 spec 同一失败签名只自主处置一次，处置后同根因复发 MUST 直接升级。

#### Scenario: 无主坏产物拯救

- **WHEN** 冻结现场的场景文件无法通过加载器校验且归属查证为非 planner 产物（如 verifier 杂交写回）
- **THEN** Arbiter 删除该文件、显式 status 解冻、触发重出题/重验，spec 恢复流转

#### Scenario: 同签名复发升级

- **WHEN** Arbiter 处置后同一 spec 同一失败签名再次触发冻结
- **THEN** 不再自主处置，直接产裁决包升级人类

#### Scenario: 白名单外不擅动

- **WHEN** 冻结原因是产品缺陷终裁类（verdict 为 bug-found 待人工取舍）
- **THEN** Arbiter 仅产裁决包（报告+选项+推荐），不改变 spec 状态

### Requirement: 调查报告与处置台账

每次 Arbiter 调查（无论处置还是升级）SHALL 产出调查报告并落处置台账：五段结构（现场快照/取证时间轴/根因/处置动作或升级理由/证据回链），报告回链归档转录、STATE 条目、git 证据等来源。

#### Scenario: 处置台账完整

- **WHEN** Arbiter 完成一次自主处置
- **THEN** 台账新增五段完整条目，含处置前后状态与证据路径回链

### Requirement: 告警零噪音分层

Arbiter 自主处置成功时，其消费的原告警 SHALL 由处置结果直接终态化（resolved_by=arbiter，附处置摘要与证据回链）：运维界面仅存一条已处理记录，MUST NOT 产生用户可感知告警（不推送、不进 pending）。处置不了/白名单外/死人开关触发时，裁决包 SHALL 同 alert_id 原位静默更新（报告进 narrative 槽位、choices/推荐注入原条目）并推入 pending 人工队列，MUST NOT 新增告警条目。

#### Scenario: 处置成功零噪音

- **WHEN** Arbiter 自主处置成功
- **THEN** 原告警终态化为已处理（resolved_by=arbiter），无 pending 推送、无新告警，运维界面可见一条已处理记录

#### Scenario: 升级包原位挂靠

- **WHEN** Arbiter 产出裁决包升级人类
- **THEN** 原告警条目被原位更新（报告+choices+推荐），进入 pending 人工队列，告警总条数不变

### Requirement: 立项节流

Arbiter 立项（框架缺口 SPEC）SHALL 受三限约束：同主题 drafted 在池即不再立项；单次调查至多 2 条；周配额缺省 5 条（超配额只记台账不落池）。立项一律落 drafted，走既有 evo ready 人审门。

#### Scenario: 重复主题不立项

- **WHEN** Arbiter 调查发现的框架缺口与 drafted 池中在审 SPEC 同主题
- **THEN** 不新建 SPEC，仅在台账记录关联指向既有 SPEC

### Requirement: 配置与 Dashboard 设置页

配置 SHALL 提供四键：`arbiter.enabled`（缺省 true）、`arbiter.budget_wallclock_s`（缺省 1800）、`arbiter.budget_tokens`（缺省 1000000）、`arbiter.max_consecutive_failures`（缺省 2）。每个配置键 MUST 在 Dashboard 设置页有对应 UI（arbiter 配置段，遵循既有设置页模式）。

#### Scenario: 设置页可见可改

- **WHEN** 用户打开 Dashboard 设置页
- **THEN** 可见 arbiter 配置段四键并可修改保存，保存后运行时按热更新语义生效

### Requirement: 关闭态零侵扰

`arbiter.enabled: false` 时，升级边行为 SHALL 与本 SPEC 合入前逐字节一致：不派发、不改道、不拦截告警、不产生 Arbiter 台账。

#### Scenario: 关闭后行为不变

- **WHEN** 配置 `arbiter.enabled: false` 且发生场景计划争议冻结
- **THEN** 冻结告警按现状路径产生并等待人工，无 Arbiter run、无台账写入

### Requirement: 车道注册与可观测性

`arbiter` SHALL 作为新 agent 类型完成全套车道注册：runner 车道表、`--add-dir` 注入白名单、config provider 段（bigmodel，model 钉 glm-5.3-flash）、`_log_lane_run_metrics` 终态指标行；在飞互斥守卫的摄取/重派匹配面 MUST 逐点核查纳入 arbiter 类型（防跨类型漏配）。运行时配置模板（`.fenix/config.template.yaml`）同步补段。生效依赖 daemon 重启——交付项含 `restart_request` 信号落位（根路径 JSON：reason/origin/date）与消费预演，实际重启由 supervisor 完成。

#### Scenario: 指标行落盘

- **WHEN** 一个 Arbiter run 到达终态
- **THEN** run_metrics 记录该 run 的 duration/turns/tokens/terminal 终态行，dashboard 可见

#### Scenario: 重启信号预演

- **WHEN** 实现完成合并后
- **THEN** restart_request 信号文件已落位且内容合法，supervisor 消费后新进程加载 arbiter 车道
