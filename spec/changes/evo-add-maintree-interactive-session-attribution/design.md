# 设计（add-maintree-interactive-session-attribution）

## 现状与根因

- 归因器本体：core/worktree_manager/mergeback.py:856 identify_wip_occupant，仅按 _INFLIGHT_LANE_RUN_PREFIXES（:847，impl-/code-fix-）过滤在飞 run 并与 git diff --name-only HEAD...<分支> 求交（:893-933）；主树直改零命中。
- 盲区自认：core/worktree_manager/types.py:27 BLIND_SPOT_NOTE；describe()（types.py:77-79）产出告警 evidence 归因文本。
- 消费者：core/worktree_manager/stray_wip.py:180-201（盘点告警，_write_alert evidence 引 info.describe()）、core/code_fix.py:3651（_coordinate_blocked_merge_impl 归因消费点，note=describe() 于 :3678/:3683，并按 info.holder 结构化写 owner_kind/owner_holders 台账 :3656-3660）、:2486/:2501（defer 升级告警 evidence 同引 BLIND_SPOT_NOTE）。（行号实测于评审时点，起草稿的 :3566/:2416 已漂移。）
- 放大机制：告警按指纹（路径集+git diff HEAD 内容哈希，stray_wip.py:239-251）一次性去重；指纹一变即重置 admin.maintree_stray_wip_grace_minutes（stray_wip.py:44-65，缺省 30 分钟）宽限再升级。
- 误报实锤样本：09:35:08Z 处置 run 1791019755 自认误报（活交互会话 a4c06558 已交付待提交）；该 run 转录已随 .fenix/runs 滚动清理、评审时不可考，方向判定以代码级盲区证据（mergeback.py:856 主树直改零命中路径 + types.py:27 盲区自认）为准，实现不依赖该转录。

## 方案决策

1. **探测源候选（实现时按可用性取舍，全部只读）**：①框架会话/交互会话注册表或锁文件（若存在可读句柄）；②git 最近提交人启发（HEAD author/committer 与项目配置身份一致且近窗口内有提交，且散件路径与其最近提交集有交）；③交互会话 transcript 目录的 mtime 活跃信号。约束：mergeback.py:952 明载「MUST NOT 为覆盖盲区引入主树写探测」——新探测必须只读；identify_wip_occupant「纯机械、不用 LLM 推导路径」的既有约束继续保持。任一候选源构成「命中」的判据 MUST 含散件与该会话的相关性信号（候选②的散件路径×最近提交集路径交，或候选①③的时间窗/工作范围交叠）——仅凭「存在活跃交互会话」MUST NOT 单独构成归因命中，否则任何无主散件（含真实滞留）都会被活跃会话吞掉。
2. **归因形态扩展而非改语义**：WipOccupantInfo 增加「会话归因」occupant kind（types.py），describe() 文案对应扩展；命中时 evidence 不再自认无主盲区，改为标注会话线索。
3. **降级留痕而非静默吞掉**：stray_wip 盘点对会话归因散件默认记 info 留痕（含会话线索与指纹记账），不派 maintree_stray_wip_stale major、不触发 admin 代查；新增配置键（如 admin.maintree_session_attribution_action，info|keep）支持回退 keep=现状行为，防误放真实滞留。指纹记账/复位逻辑复用现状（stray_wip.py:217-251）。配置键为全局回退开关：code_fix defer 侧（:3651 消费点）对会话归因的采信受同键约束——keep 时 defer 侧把会话归因视同零命中走现状 orphan 宽限升级流（owner_kind=orphan），防止「盘点侧可回退、defer 侧无开关」的不对称。会话归因 holders 无 run_ids，defer 侧自然不注册终态回调（事件驱动重试缺席、既有轮询兜底在场，行为安全）。
4. **消费同步**：code_fix.py 两处消费者（:3651、:2486/:2501）复用归因结果但不复制探测。注意 :3651 不止透传文本——owner_kind 随 info.holder 翻转（:3656-3660 结构化台账）、orphan 计时清零，这正是会话归因对 defer 侧的「透明生效」面，其升级抑制由决策 3 的配置键对称回退兜底；:2486/:2501 仅 evidence 文本随 describe()/BLIND_SPOT_NOTE 扩展。

## 风险

- 探测源①可能不存在（框架无会话锁机制）——候选②③兜底，且探测失败 fail-open 回现状，无行为回归。
- 会话归因可能误放真实滞留（会话活跃但成果已被遗忘）——info 留痕保留完整证据链 + 配置开关可回退；观察一段窗口后再调默认值。