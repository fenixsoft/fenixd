## Deliverables

```yaml
- path: core/pm_engine/arbiter.py
  kind: new
- path: core/agent_runner/runner.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: core/adjudication_narrative.py
  kind: modify
- path: agents/arbiter.md
  kind: new
- path: core/dashboard/routes/settings_routes.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/ArbiterPanel.tsx
  kind: new
- path: tests/test_arbiter_lane.py
  kind: new
- path: tests/test_arbiter_guardrails.py
  kind: new
- path: .fenix/config.template.yaml
  kind: modify
- path: restart_request
  kind: new
```

设计真相源：`docs/superpowers/specs/2026-10-31-arbiter-lane-design.md`（fbeb3f104）。权限强制层级=提示词红线+台账审计（用户裁定）；裁决包挂原告警静默更新；自主处置零用户可感知告警。

## 1. 触发面与改道注册（咽喉层）

- [x] 1.1 core/state_machine.py：freeze_for_human 咽喉挂 Arbiter 派发注册（经回调解耦，enabled 且机器发起时入队），排除表落地：freeze_spec（人工冻结）/mark_frozen_hold（簿记）/frozen_until 定时冻结三路径零接触；arbiter.enabled:false 时全路径行为与现状逐字节一致
- [x] 1.2 core/pm_engine/family.py：_send_human_escalation_alert 对 blocked/frozen/场景争议类 condition 注册 Arbiter 派发；token 预算耗尽、spec_integrity 内容缺失、queue 异常 condition 显式排除（留 narrative 与人类）
- [x] 1.3 dedup+单飞+死人开关（core/pm_engine/arbiter.py）：同 spec 同失败签名只派发一次；全局单飞队列串行（排队登记失败 MUST 显式报错不得吞 conflict 报假成功——scheduling_kick 前科）；同触发连败达 max_consecutive_failures（缺省 2）或单 run 超 budget_wallclock_s/budget_tokens → 停止自主尝试、半成品调查包按挂靠语义升级

## 2. arbiter 车道注册

- [x] 2.1 core/agent_runner/runner.py：arbiter 类型全套注册——车道表、--add-dir 注入白名单、run 命名 arbiter-<spec>-<ts>、_log_lane_run_metrics 终态指标行；在飞互斥守卫摄取/重派三处匹配面逐点核查纳入 arbiter 类型（bc3c07e8 跨类型漏配前科，核查点以注释清单留痕）
- [x] 2.2 .fenix/config.template.yaml：arbiter provider 段（bigmodel、model 钉 glm-5.3-flash）与角色枚举注释补 arbiter 行；config 读取链补四键（enabled/budget_wallclock_s/budget_tokens/max_consecutive_failures，缺省 true/1800/1000000/2），运行时 config.yaml 缺段走缺省（reference 语义：真实 .fenix/config.yaml 非本仓交付物）
- [x] 2.3 restart_request 信号落位（仓库根，JSON：reason/origin/date，reason 注明「arbiter 车道注册需 daemon 重启加载」）+ 消费预演（全新进程 import 链 + 咽喉注册自检断言），实际重启由 supervisor 消费信号完成

## 3. 提示词与权限红线

- [x] 3.1 agents/arbiter.md：永不可碰 5 类置顶红线段（证据源只读/禁伪造 run 产物/禁 push 禁改 main/禁绕过 flock/禁动进程管理面）+ 许可清单 6 类知情违规 + 升级偏向段（不确定即升级、假阴性/假阳性不对称论证、同签名只自主处置一次复发即升级）+ 五类白名单鉴定要点（①冻结场景文件拯救含无主产物鉴定双判据②裁决落位考古③验证侧计数复位④陈锁清扫⑤WIP 门分拣）+ 立项节流三限 + 调查报告五段格式与裁决包格式契约段（契约段遵循 prompt 文件化纪律）
- [x] 3.2 红线契约测试：agents/arbiter.md 关键禁令词目与段落存在性机械断言（agents 契约段测试既有范式），漏段即测试红

## 4. Arbiter 调查与处置执行面

- [x] 4.1 core/pm_engine/arbiter.py 主流程：触发消费→调查 run 启动（dsh 车道，含记忆检索上下文注入）→结果分类（处置成功/升级/失败）→处置动作直执行（StateMachine.unfreeze_spec 显式 status、验证计数清零、删除经双判据鉴定的无主坏产物、复位重派、主树 spec 目录在飞改动提交）；预算记账贯穿 run 生命周期
- [x] 4.2 处置台账：五段结构（现场快照/取证时间轴/根因/处置动作或升级理由/证据回链）持久化（对照 admin 处置族台账范式扩展），dashboard 数据层可读
- [x] 4.3 告警零噪音分层：处置成功→原告警直接终态化 resolved_by=arbiter（附处置摘要+证据回链，不推送不进 pending）；升级→同 alert_id 原位静默更新（调查报告进 narrative 槽位、choices+recommended_action 注入原条目）并推 pending 人工队列；两路径均不新增告警条目
- [x] 4.4 立项节流写点：同主题 drafted 在池查重（主题/capability 级匹配）、单次调查至多 2 条、周配额 5（超配额只记台账）；立项一律 status 落 drafted

## 5. narrative 让位与 Dashboard

- [x] 5.1 core/adjudication_narrative.py：blocked/frozen 类告警的后台补叙让位 Arbiter 报告（原位更新叙事槽位，见 4.3），非阻塞类 narrative 行为不变；让位与 arbiter.enabled 联动（关闭时 narrative 照旧）
- [x] 5.2 core/dashboard/routes/settings_routes.py：arbiter 配置段读写端点（四键，校验与既有设置段一致）
- [x] 5.3 core/dashboard/static/src/pages/settings/components/ArbiterPanel.tsx（new）+ index.tsx 挂载：设置页 arbiter 段四键 UI，遵循既有面板模式与仓库根 DESIGN.md（无偏离条款）

## 6. 测试

- [x] 6.1 tests/test_arbiter_lane.py：触发面五态（机器冻结触发/人工冻结不触发/定时冻结不触发/condition 排除两类）、同签名 dedup、单飞排队与排队失败显式报错、死人开关（连败 2 次/墙钟超限/token 超限三路径均产半成品包升级）、显式 status 解冻断言（非 ready、实现成果保留）
- [x] 6.2 tests/test_arbiter_guardrails.py：红线契约断言（3.2）、同签名复发直接升级、白名单外只产裁决包不擅动、处置成功零噪音（原告警终态化 resolved_by=arbiter+零新增条目断言）、升级原位挂靠（同 alert_id+条数不变+pending 入队）、关闭态零侵扰（enabled:false 全路径现状对照）、台账五段完整、_log_lane_run_metrics 指标行落盘、立项节流三限、narrative 让位与非阻塞类不受扰
