# Arbiter 自主裁决车道

<!-- knowledge: capability=arbiter-lane rev=2
     sources=spec/archive/2026-11-03-add-arbiter-lane,spec/changes/add-arbiter-backlog-sweep,spec/changes/add-escalation-chain-admin-arbiter,spec/knowledge/_inbox/done/chain-arbiter-rulings-default-3.md -->

Arbiter agent 对升级边信号做自主调查与处置/拍板的车道：处置链第二级（全局视野），链路由与配额语义见 [escalation-chain](escalation-chain.md)。

## 规则

- 触发面注册在升级边两个咽喉层：`StateMachine.freeze_for_human`（机器「冻结+告警」成对单一入口）与 `PMEngine._send_human_escalation_alert`。触发面为黑名单制——默认全部升级边信号入处置链，仅黑名单配置内信号绕过全链直达人工队列。
- 以下事件不触发链派发：`freeze_spec`（dashboard 人工冻结）、`mark_frozen_hold`（冻结终止簿记）、`frozen_until` 定时冻结（scheduled-unfreeze 自愈在先）。
- 全局单飞：同一时刻至多一个 Arbiter run，后续触发排队串行，单飞队列深度上限固定。
- 同签名派发受配额治理：Admin 尝试配额 2 次/签名、Arbiter 复现配额缺省 3 次/签名（缺省单源 `ConfigLoader.CHAIN_ARBITER_RULINGS_DEFAULT`），复位窗 7 天或 spec 状态迁移清零；dead-man/停机类签名维持永久单次。
- 存量回扫：daemon 启动（`arbiter.enabled=true`）与 config 热更新 disabled→enabled 跃迁时各执行一次——扫描 STATE 中 `frozen=true` 且 `admin_alerts` 存在同 spec 未处理（pending）机器升级告警的存量 spec（`frozen_until` 非空的定时冻结排除），命中者经链管线入队派发（链头 Admin，沿用 dedup/单飞/预算约束）；回扫幂等，与事件触发共用同签名 dedup；回扫哨兵与存量迁移哨兵互不重入（回扫消费在案 pending 入链派发，迁移只收口已闭环 pending 且不回填入链）。
- 自主处置白名单五类：①冻结场景文件拯救（无主产物鉴定：加载器校验失败+归属查证非 planner 产物→删除+显式 status 解冻）；②裁决落位/verdict 缺失考古；③验证侧计数冻结复位（impl run 预算上调由预算豁免拍板动作面承接）；④worktree 陈锁清扫；⑤WIP 门/在飞闸门分拣提交。②⑤鉴定成本过高时允许降级为「首期落地①③④，②⑤只产裁决包不处置」并在 design.md 注明。
- 白名单外（产品缺陷终裁、无考古证据的场景集语义取舍、逻辑矛盾）只产裁决包（报告+选项+推荐），不擅动状态；预算政策类由 Arbiter 预算豁免拍板动作面承接（写 spec 预算 override 字段+台账留痕）。
- run 预算封顶：墙钟与 token 双预算约束（缺省 1800 秒 / 1000000）；同签名失败连续达阈值（缺省 2 次）或预算耗尽时停止继续自主尝试，半成品调查包按裁决包挂靠语义升级人类，不静默死亡（不落账不通知）。
- 权限红线（提示词级+台账审计，不做机械强制）：`agents/arbiter.md` 载明许可清单（显式 status 解冻、端点四步语义直执行、验证计数清零、删除经鉴定无主坏产物、复位重派、主树 spec 目录在飞改动提交六类知情违规）与永不可碰五类（runs 归档/记忆目录/admin_alerts 归档等证据源只读；禁伪造 run 产出形态文件；禁 push、禁改 main 产品代码、禁手工 merge 产品分支；禁绕过 flock 直写 STATE；禁动 daemon.lock/supervisor）。解冻必须经 `StateMachine.unfreeze_spec(name, status=...)` 显式传状态，禁止依赖缺省状态解析。
- 每次调查（无论处置还是升级）产出五段处置台账：现场快照/取证时间轴/根因/处置动作或升级理由/证据回链，报告回链归档转录、STATE 条目、git 证据等来源。
- 告警零噪音分层：自主处置成功时原告警由处置结果直接终态化（resolved_by=arbiter，附处置摘要与证据回链），运维界面仅存一条已处理记录，不推送、不进 pending；处置不了/白名单外/死人开关触发时，裁决包同 alert_id 原位静默更新（报告进 narrative 槽位、choices/推荐注入原条目）并推入 pending，告警总条数不变。
- 立项节流三限：同主题 drafted 在池即不再立项；单次调查至多 2 条；周配额缺省 5 条（超配额只记台账不落池）。立项一律落 drafted，走既有 evo ready 人审门。
- 配置四键带 Dashboard 设置界面：`arbiter.enabled`（缺省 true）、`arbiter.budget_wallclock_s`（缺省 1800）、`arbiter.budget_tokens`（缺省 1000000）、`arbiter.max_consecutive_failures`（缺省 2），保存后按热更新语义生效。
- 关闭态零侵扰：`arbiter.enabled: false` 时升级边行为与无 Arbiter 时代逐字节一致——不派发、不改道、不拦截告警、不产生 Arbiter 台账。
- 车道注册全套：runner 车道表、`--add-dir` 注入白名单、config provider 段（bigmodel，model 钉 glm-5.3-flash）、`_log_lane_run_metrics` 终态指标行；在飞互斥守卫的摄取/重派匹配面逐点核查纳入 arbiter 类型（防跨类型漏配）；运行时配置模板（`.fenix/config.template.yaml`）同步补段。生效依赖 daemon 重启，交付项含 `restart_request` 信号落位与消费预演，实际重启由 supervisor 完成。

## 溯源

- 2026-10-31 add-arbiter-lane（spec/archive/2026-11-03-add-arbiter-lane/） — 新增本页基线：触发面注册与单飞、run 预算封顶、权限红线许可清单、自主处置白名单、五段处置台账、告警零噪音分层、立项节流、配置与关闭态、车道注册
- 2026-10-31 add-arbiter-backlog-sweep（spec/changes/add-arbiter-backlog-sweep/） — 触发面扩增存量冻结回扫（daemon 启动与热更新跃迁各一次，幂等回扫）
- 2026-11-03 add-escalation-chain-admin-arbiter（spec/changes/add-escalation-chain-admin-arbiter/） — 触发面白名单枚举改黑名单制默认入链；同签名「只派发一次」改配额治理（2 次/签名+复位窗，dead-man 永久单次例外）；白名单③放开 impl run 预算上调（预算豁免拍板面承接）；回扫管线接入链头 Admin
- 2026-11-03 chain-arbiter-rulings-default-3（spec/knowledge/_inbox/done/chain-arbiter-rulings-default-3.md） — 折叠 Arbiter 复现配额缺省调整为 3 次/签名（配额语义与复位通道不变）
