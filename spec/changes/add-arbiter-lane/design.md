## Context

冻结族事故两次验尸（2026-10-26/27 add-command-center、2026-10-30/31 evo-refine-midflight-outlier-dims）证明：阻塞升级人类时，自主恢复只有复位重试一招，验尸知识碎片化五处，人类被降格为验尸官。本 SPEC 把「框架外验尸者」制度化：升级边改道为 冻结→Arbiter→（大多数）自主处置 /（少数）带裁决包升级。

**设计真相源**：`docs/superpowers/specs/2026-10-31-arbiter-lane-design.md`（commit fbeb3f104，148 行完整设计，含用户四项裁定）——实现前必读，本文只载绑定决策与实现要点，不复制全文。

builder 核查已确认的代码锚点：`StateMachine.unfreeze_spec(name, status=...)`（`core/state_machine.py:2351`，显式 status 已内置绕过 parse_orig_status ready 兜底）；升级发射收敛于 `freeze_for_human`（`state_machine.py:2168`）与 `PMEngine._send_human_escalation_alert`（`core/pm_engine/family.py`）两咽喉；choices 注册表与 alert-resolve 闭环已落地（`core/adjudication_narrative.py`）；现有 agent run 以 `permission_mode="bypassPermissions"` spawn（`runner.py:6401`）——无现成路径级强制，权限边界按用户裁定走提示词红线。

## Goals

1. 冻结→人类的边改道：大多数阻塞由 Arbiter 自主处置闭环，人类只收裁决包签字。
2. 自主处置成功零用户可感知告警（运维界面一条已处理记录）。
3. 类级框架缺口经 Arbiter 立项进入既有进化循环，攻击组合爆炸。

## Decisions（绑定，含用户裁定）

1. **mode=full、立即执行**（用户指定）。
2. **权限强制层级 = 纯提示词红线 + 台账审计**（用户裁定 2026-10-31）：不建白名单动作执行器、不建 per-run deny hooks。后果如实接受：越线无机械闸，故 s5（诱导越线拒绝）与 s7（台账完整）为一级验收场景。
3. **裁决包挂靠 = 同 alert_id 原位静默更新**（用户裁定）：不新增告警条目，dedup 与 alert-resolve 沿用原告警；需拍板才推 pending。
4. **告警零噪音分层**（用户补充裁定）：自主处置成功→原告警直接终态化（resolved_by=arbiter），零推送零 pending；仅升级类进 pending。
5. **触发面排除表**：freeze_spec（人工在场）、mark_frozen_hold（簿记影子）、frozen_until（定时自愈赛跑）、token 预算/spec_integrity/queue 异常（政策与数据完整性）一律不触发。
6. **同签名只自主处置一次**：处置后同根因复发直接升级（10-31 第 2 轮同根因复发教训）。
7. **立项节流三限**：同主题 drafted 在池不重复、单次 ≤2 条、周配额 5（evo 自动接受前科对齐）。
8. **双路分离**：解阻塞=状态修复+重派（红线内直接做）；修框架=SPEC 落 drafted 走既有循环，Arbiter 不亲手改产品代码。
9. **车道形态**：agent 类型 `arbiter`、dsh harness、bigmodel 网关、model 钉 glm-5.3-flash（narrative 车道 10-09 前科：不钉则踩 [1M] 别名秒挂）。
10. **生效方式**：daemon 不随合并自动重启——交付 restart_request 信号落位+预演，实际重启由 supervisor 消费（dashboard 类 SPEC 既有纪律）。

## 界面约束

Dashboard 设置页 arbiter 配置段遵循既有设置页模式；设计约束以仓库根 `DESIGN.md` 为准，本 SPEC 无偏离条款。

## Risks

1. **软护栏被越线**（最大风险）：红线无机械闸。缓解：提示词红线醒目置顶 + 台账全审计 + s5/s7 一级验收 + `arbiter.enabled` 总开关可随时关闭。
2. **误判处置**：升级偏向写死（假阴性无害、假阳性危险）；首期白名单仅配方成熟类；实现者可降级为①③④三类（②⑤只产裁决包）——降级不视为缩水。
3. **新 agent 类型注册遗漏**：互斥守卫跨类型漏配有 bc3c07e8 前科——摄取/重派匹配面逐点核查列为交付任务。
4. **告警面回归**：narrative 让位仅限 blocked/frozen 类，非阻塞类叙事行为不变；关闭态零侵扰（s8）兜底。

## 留给实现者的空间

- 咽喉层钩子形态（回调注册 vs 事件订阅）按 pipeline/family 现有风格定。
- 台账文件 schema 对照 admin 处置五段模板扩展。
- 单飞队列实现自行权衡，但必须避开 scheduling_kick 单槽位「写侧吞 conflict 报假成功」前科。
- 首期白名单可按成本降级（见 Risks 2），在实现说明中注明即可。
