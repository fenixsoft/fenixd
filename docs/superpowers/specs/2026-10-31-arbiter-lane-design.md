# 全局决策者车道（Arbiter）设计

日期：2026-10-31
状态：定稿待批
预期立项：add-arbiter-lane（mode: full）

## 1. 意图与 why

冻结族事故两次验尸（10-26/27 add-command-center、10-30/31 evo-refine-midflight-outlier-dims）实证出同一个结构性缺陷：

1. **自主恢复工具箱只有「复位重试」一招**——对瞬态失败有效，对持久化状态污染无效（两任 admin 复位重派 4 次全部撞同一坏文件）。
2. **验尸知识碎片化**——解开一次阻塞所需的证据分散在归档转录、STATE、源码契约、git 历史、蒸馏记忆五处，没有任何一个在飞 agent 的信息面同时覆盖。
3. **人类被降格为验尸官**——冻结信息给的两个菜单选项都隐含要求处置者先完成跨车道取证，等于要求人工到场后从零重建现场。
4. **按例打补丁追不上组合爆炸**——守卫补上一场事故的弹孔，下一场总从没设防的墙面进来；类级治理需要先有跨车道验尸者。

本设计把「框架外验尸者」的四个结构性优势（全链视野、跨车道权限、记忆、知情违规权）**制度化**：冻结→人类的升级边改道为 **冻结→Arbiter→（大多数）自主处置 /（少数）带完整调查包升级人类**。

## 2. 目标

1. 冻结/转人工事件自动触发 Arbiter run（新 agent 类型 `arbiter`，dsh 车道）。
2. 自主调查：全链视野（daemon 日志、run 归档转录、STATE、源码契约、git 历史、记忆库）。
3. 自主处置：许可清单内的状态修复与重派。
4. 自主立项：调查中发现的类级框架缺口 → SPEC 落 drafted（走既有 evo ready 人审门）。
5. 处置不了的 → 裁决包（调查报告+处置选项+推荐）进 choices 注册表，人类从验尸官变签字人。
6. **告警面零噪音分层（用户补充 2026-10-31）**：Arbiter 自主处置成功的，其消费的告警**由处置结果直接终态化**（resolved_by=arbiter，附处置摘要与证据回链）——运维界面仅存一条「已处理」记录，**不产生任何用户可感知告警**（不推送、不进 pending）；仅升级类（裁决包）推入 pending 人工队列。
7. 替代 admin 告警 narrative 车道中 blocked 类的调查内容（narrative 保留给非阻塞类告警）。

## 3. 非目标

- **不替代 Administrator 车道**：admin 仍是在飞处置第一响应；Arbiter 只消费 admin 处置不了而升级的边。
- **不直接改产品代码**：修框架一律走 SPEC 循环（drafted→ready→implementer 分支→验证→合并），Arbiter 自己不亲手改任何产品代码。
- 不处理车道内常规失败（各有既有恢复路径）。

## 4. 反目标（出现即失败）

- **伪造 provenance**：手工造「run 产出」形态的裁决/verdict/报告入账。
- **静默死亡**：预算耗尽或连败后不升级、不落账。
- **无审计动作**：任何状态变更不留台账五段。
- **过度处置**：把白名单外/该升级的也自己拍板。

## 5. 权限许可清单

### 5.1 白名单（允许的「知情违规」）

1. 直呼 `StateMachine.unfreeze_spec(name, status=...)` 显式传 status（绕过 `parse_orig_status` 的 ready 兜底——10-26 前科配方）。
2. 端点四步语义 Python 直执行（admin 处置族解卡配方）。
3. 验证计数器清零/复位（随 unfreeze 原子写）。
4. 删除**经鉴定为无主坏产物**的文件（无法通过加载器校验 + 归属查证非 planner 产物，如 10-31 的 verifier 杂交写回）。
5. 复位重派（blocked→testing 等门转移、verifier/planner 入队）。
6. 提交主树 spec 目录在飞改动（既有 admin 处置先例，4c520ff7a）。

### 5.2 永不可碰（安全姿态裁定 2026-10-31：提示词红线+审计兜底，不做机械强制）

> 用户裁定：权限边界以提示词红线+台账审计（s7）实现，**不建**白名单动作执行器、**不建** per-run deny hooks 新基建（现状所有 agent 本就以 `bypassPermissions` spawn，`runner.py:6401`，无现成路径级强制可复用）。后果如实记录：越线无机械闸，红线与审计是唯一防线——故提示词契约段核查与审计完整性在验收场景中为一级场景（s5/s7），不是附属项。

1. **证据源只读**：runs 归档、记忆目录、admin_alerts 归档、`.history` 外的蒸馏产物。Arbiter 是唯一有动机篡改证据的实体。
2. **禁伪造 run 产出**：不写任何「框架读侧会当作 run 产物消费」的文件（verdict、report.json、result 文件）。修复只能选：重派让真 run 产出，或升级人类。
3. 禁 `git push`、禁直接改 main 产品代码、禁手工 merge 产品分支（merge 走框架收口链）。
4. 禁绕过 flock 直写 STATE（一律过 `StateMachine.update_spec`）。
5. 禁动 daemon.lock / supervisor / config.yaml 之外的进程管理面。

## 6. 双路分离

- **解阻塞** = 状态修复 + 重派，白名单内直接做，事后台账。
- **修框架** = 调查中发现的类级缺口 → SPEC 落 drafted 即止（evo ready 门人审）。初期不开自动 ready；战绩积累后可对低风险类（测试补齐、告警文案）开 fast-track 白名单——此为后续 SPEC，不在本期。

## 7. 首期类白名单（可自主处置）

1. **冻结场景文件拯救**：dict/杂交形态鉴定、无主产物认定（对照 planner 产物归属与时间轴）、删除 + 显式 status 解冻（10-26/10-31 两次实证配方）。
2. **裁决落位/verdict 缺失类**：转录考古找回裁决、落位契约对照（prompt_builder {result_path} 白名单语义）、判「重派重验」还是「升级」。
3. **验证侧计数冻结复位**：重验计数清零配方族（unfreeze 原子写已内置）。**不含 impl run 预算上调**——那是预算政策类决定，留白名单外。
4. **worktree 陈锁清扫**：终态 run 残锁鉴定与清扫（fix-worktree-lock-release-degrade-gate 语义之外的存量）。
5. **WIP 门/在飞闸门阻塞**：主树在飞改动分拣提交 + 复位（hunk surgery 处方）。

**白名单外（必须升级人类）**：产品缺陷终裁（bug-found 后的打回/接受取舍）、场景集语义取舍且无考古证据可定（「过时 vs 可修」依赖用户路线图知识时）、逻辑矛盾（守卫互斥、双计数口径打架且修法互相冲突）、预算政策类决定、Arbiter 自身权限边界争议。

## 8. 升级偏向（写死在提示词）

- **不确定即升级**。假阴性（该自己处理却升级）代价 = 一次人工点击；假阳性（该升级却自作主张）代价 = 污染台账/烧预算/错误修复。不对称，故偏向升级。
- 每次调查必产调查报告（无论处置还是升级），落处置台账并回链证据。
- 处置后必须验证：复位后 spec 在预算内正常流转才算处置成功；复位即复发 = 升级信号，不进第二轮自主处置（对应 10-31 的「第 2 轮同根因复发」教训——**同一 spec 的同一失败签名只自主处置一次**，复发即升级）。
- **立项节流（evo 自动接受前科对齐）**：同主题 drafted 在池即不再立项；单次调查至多 2 条 SPEC；周配额缺省 5 条，超配额只记台账不落池。落提示词契约 + 立项写点 + 验收场景。

## 9. 触发与插入点

- **信号保留**：争议计数器、blocked_stuck 15min、human-escalation-alert 等既有触发器全部不动。
- **插入点收敛（builder 核实）**：升级发射实际收敛于两个咽喉——`freeze_for_human`（`state_machine.py:2168`，机器「冻结+告警」成对单一入口）与 `PMEngine._send_human_escalation_alert`（`pm_engine/family.py`）。改道注册落**咽喉层**，不做调用方逐点注册。
- **触发面（builder 问题 1 裁定）**：
  - **进**：`freeze_for_human` 全族（fast_track 三处、impl 验证/重做预算冻结、dispatch queue、verify_redo 等）+ `_send_human_escalation_alert` 中 blocked/frozen/争议类 condition。
  - **不进**：`freeze_spec`（dashboard 人工冻结——人已在场，Arbiter 插手是噪音且与未终止在飞 run 竞态）；`mark_frozen_hold`（冻结终止簿记，是 freeze 的影子非独立事件）；`frozen_until` 定时冻结（`engine.py` scheduled-unfreeze 自愈在先，进触发面会与定时自解冻赛跑）；token 预算耗尽、spec_integrity 内容缺失、queue 异常类告警（政策/数据完整性，留 narrative 与人类——与 §7 白名单外清单一致）。
- **dedup**：同 spec 同签名只派发一次；全局单飞队列串行——决策点是低频高价值动作，不并行。
- **死人开关**：Arbiter run 失败连续 N 次（缺省 2）或预算耗尽 → 带半成品调查包升级人类，禁止静默死亡（12h 悬空 run 前科）。

## 10. 车道形态

- 新 agent 类型 `arbiter`：`agents/arbiter.md` 提示词（许可清单+类白名单+升级偏向+报告格式契约段）；runner 注册（对照 administrator 的注册点：runner.py 车道表、--add-dir 注入白名单、config provider 段、`_log_lane_run_metrics` 指标行）。**新增类型必须逐点核查在飞互斥守卫的摄取/重派匹配面**——跨类型漏配有 bc3c07e8 前科。
- dsh 车道，bigmodel 网关，model 钉 glm-5.3-flash（narrative 车道 10-09 前科：不钉则踩 [1M] 别名秒挂）。
- run 命名 `arbiter-<spec>-<ts>`；supervisor/排水/restart_request 语义与 admin 车道一致。
- Dashboard：admin 处置族同款可见性 + 车道指标行 + 设置页新增配置段（每键必带 UI——既有纪律）。

## 11. 配置（每键必带 Dashboard 设置页）

```yaml
arbiter:
  enabled: true                # 总开关
  budget_wallclock_s: 1800     # 单次调查墙钟预算（默认 30min）
  budget_tokens: 1000000       # 单次调查 token 预算
  max_consecutive_failures: 2  # 死人开关阈值
  # 类白名单内置代码（不进配置），auto_handle_classes 留待战绩后开放
```

## 12. 与既有部件的关系

| 部件 | 关系 |
|---|---|
| Administrator 车道 | 不变；Arbiter 是其处置失败后的升级消费者 |
| adjudication_narrative | blocked/frozen 类告警的调查叙事由 Arbiter 报告替代；narrative 保留给非阻塞类 |
| choices 注册表 + alert-resolve | Arbiter 的裁决包是 choices 的首要高质量供给方（含 recommended_action）。**挂靠语义（用户裁定 2026-10-31）：同 alert_id 原位静默更新**——报告进 narrative 槽位、choices/推荐注入原条目，需拍板时才推 pending 人工队列；不新增告警条目，dedup 与 alert-resolve 闭环沿用原告警 |
| evo 车道 | Arbiter 立项的 SPEC 进同一 drafted 池，走同一 ready 门 |
| 冻结族三治理 SPEC（10-27） | 语义兼容：读端 salvage、verdict 归属戳、陈锁释放继续生效；Arbiter 处理它们覆盖不到的组合态 |

## 13. 验收场景（Scenario 形态）

1. **s1 无主坏产物拯救**：造 dict 场景文件 + 冻结 → Arbiter 自动鉴定（归属查证 + 加载器校验）→ 删除 → 显式 status 解冻 → 重出题 → spec 恢复流转；台账五段齐全、解冻 status 非 ready；**全程零用户可感知告警**——原冻结告警被处置结果直接终态化（resolved_by=arbiter），运维界面仅见一条已处理记录。
2. **s2 白名单外升级**：产品缺陷类冻结 → Arbiter 产裁决包**原位挂原告警**（同 alert_id，choices+推荐注入，不新增告警条目），不擅动状态。
3. **s3 死人开关**：连续 2 次 run 失败 → 半成品调查包升级，无静默。
4. **s4 预算耗尽**：超墙钟/token 预算 → 同 s3。
5. **s5 权限负面**：构造诱导（要求伪造 verdict / 改 main 代码）→ 拒绝并升级。
6. **s6 同签名复发升级**：处置后同根因复发 → 第二次不再自主处置，直接升级。
7. **s7 全审计**：每个 Arbiter run 有 run_metrics 行 + 处置台账 + dashboard 可见。
8. **s8 关闭态零侵扰**：`arbiter.enabled: false` → 升级边行为与现状逐字节一致。

## 14. 交付物预估

- `core/pm_engine/arbiter.py`：触发钩子注册、dedup、单飞队列、死人开关、派发
- `core/agent_runner/runner.py`：arbiter 类型注册（车道表/注入白名单/指标行）
- `agents/arbiter.md`：提示词（契约段落遵循 prompt 文件化纪律）
- `core/pm_engine/verification/pipeline.py` 等五处升级边：改道注册（保留原信号）
- `core/adjudication_narrative.py`：blocked 类叙事让位逻辑
- dashboard：设置页 arbiter 段 + 车道视图
- `tests/test_arbiter_*.py`：覆盖 s1-s8

## 15. 留给实现者的决策空间

- 钩子具体形态（事件订阅 vs 写点直调）按 pipeline 现有风格定。
- 调查报告的持久化形态（台账文件 schema）对照 admin 处置五段模板扩展。
- 单飞队列实现（内存队列 vs 现有 scheduling_kick 槽位语义）自行权衡，但**写侧吞 conflict 报假成功的前科（scheduling_kick 单槽位）必须避开**。
- 首期五类白名单的鉴定逻辑若实现成本过高，可首期先落 1/3/4 三类（配方最成熟），2/5 类降级为「只产升级包不处置」——降级不视为缩水，在 SPEC 中注明即可。
