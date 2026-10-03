# 设计：upgrade-narrative-to-investigation

## Context

add-adjudication-alert-narrative 落地后的实测缺陷（2026-10-04 取证）：

- **能力**：`adjudication_narrative._build_prompt` 输入仅有机械字段原文 + choices + STATE 三行 + 报告**路径存在性**。模型被明确禁止编造（「材料里没有的信息不要编造」），因此只能复述 description/evidence——决策者仍需另行询问 AI 做根因调查（android-station-port judge_rerun_cap 实证：真正有用的是「6 次派发去向 + env 握手死循环」的因果链，而这不在任何喂入材料里）。
- **可靠性**：potplayer-base 45 条告警 0 条 narrative（两次「输出为空/超时」WARNING）；judge_rerun_cap 告警因同步叙事延迟 60.58s 落盘（恰为 `narrative_timeout_seconds=60` 整窗），同期网关 stall 188s/191s（fenixd.log 多处）。同步设计使叙事失败成本直接加在**裁决及时性**上——与该 SPEC 的立项初衷（「裁决贵在及时」）相反。

## Goals / Non-Goals

**Goals**

1. 叙事从「白话转述」升级为「有据调查」：决策者读 narrative 即可裁决，无需再问；
2. 告警落盘路径零阻塞（叙事时延与失败都不影响告警及时性）；
3. 网关事故期叙事退化为零成本（熔断），不放大故障。

**Non-Goals**

- 不改告警本体 schema 与 alert-resolve 闭环（choices/trigger/处置零感知）；
- 不做叙事结果的结构化抽取（仍是人类可读 Markdown，不供机器消费）；
- 不做跨项目/跨告警的叙事缓存；
- 不改模型路由策略（`admin.narrative_model` 回退链维持现状，调优属配置层）。

## Decisions

### D1：证据采集走「标准产物路径约定」，发射点 facts 为可选增强

通用采集器按信号族从固定路径读取（verification-report.md / report.json / verdict_stability.json / fail_history.json），**发射点零改动即可获得调查材料**——这是主通道。`facts` 透传（发射点内存中独有、事后难重建的信息，如 judge 派发台账）作为 `escalation_notifier` 新可选参数，为第二期增强点，本期仅预留参数位与 prompt 段（facts 存在时注入，缺省不注入不破坏）。

理由：本证（android-station-port）的调查结论所需的全部事实——验证报告（含 bug 与 env 豁免清单）、判定轮次、失败演进——都在标准产物里；先打通主通道收益最大、改动最小。

### D2：异步补叙用侧车文件，不改 admin_alerts.json 本体

`admin_alerts.json` 记录 append 后不可变（alert-resolve/闭环判定按 id 操作本体），原地补写 narrative 会引入「读改写整文件」的并发窗口与迁移成本。侧车 `.fenix/admin_alerts_narrative/<alert_id>.json`（原子写）+ 读侧按 alert_id 合并，是零迁移、零并发风险的增量形态。

- 告警清理路径（既有保留上限/归档清理）追加侧车级联删除，防孤儿堆积（归档视图不含 narrative 属预期——侧车只服务活跃告警集）；
- 生成失败/熔断跳过写**终态侧车**（同构，text 为机械说明、model 为 null），读侧 pending 判定即「侧车文件缺失」，失败告警渲染失败说明而非悬挂「调查生成中」假态；
- 前端 `AlertNarrative` 已按 `narrative` 字段渲染——读侧合并后字段形态不变，前端增量仅「调查生成中」占位（侧车缺失且告警未 handled 时显示）。

### D3：prompt 四段化 + 反编造规则收窄

「调查结论」段独立成段的理由：转述（发生了什么）与归因（调查结论）的认知任务不同，混在一段会诱导模型用现象复述填充根因。指令明确「引用具体证据（计数器/预算/环境事实）」，反编造收窄为三句式：材料内有据必须给、材料外不得编、不足要明说并给查证路径——比旧规则（「没有的信息不要编造」）更可执行，避免模型因过度保守输出空段落导致结构校验失败。

机械校验四段升级，旧三段输出判失败走兜底——**不兼容旧输出是故意的**（三段输出意味着模型没读到新指令，材料大概率也没喂进去，落机械文案比落半截调查更诚实）。

### D4：熔断器用进程内滑动计数，不持久化

连续失败计数与冷却窗口存 daemon 进程内（模块级状态）：daemon 重启即复位——可接受，熔断的敌人是「网关事故期的连续白烧」，重启本身已重置了该场景。持久化会引入「熔断状态陈旧」新问题（重启后该试不试），得不偿失。窗口 1 小时与 `escalation_cooldown_minutes`（缺省 60 分钟）量级对齐。复位语义：冷却期内零调用，不存在「期间成功」路径；到期恢复尝试后一次成功即清零计数。

### D5：超时 180s + 至多 2 次尝试

网关 stall 实测 p90 ≈ 55s、max ≈ 188s（judge run latency 统计）——60s 超时把长尾全判死。180s 覆盖 max 档；异步化后超时成本不再落在告警路径上，放宽无副作用。2 次尝试封顶防重试风暴（熔断器是第二道闸）。

## Risks / Trade-offs

- **[侧车孤儿]** 告警被清理而侧车残留 → 清理路径级联删除（D2）；清理失败残留侧车仅占磁盘、渲染按 alert_id 匹配不到即忽略，无害。
- **[异步时序]** 告警落盘后数秒内人工刷新看不到 narrative → 前端「调查生成中」占位 + 既有轮询自然补齐；处置动作不依赖 narrative（choices 独立渲染）。
- **[四段校验更严]** 模型能力不足时三段→四段失败率上升 → 兜底语义不变（机械文案落盘），熔断器兜成本；且失败即 WARNING 留痕可观测。
- **[材料注入的提示注入面]** 验证报告内容进入 prompt → 报告由框架合成/评审 agent 产出，信任边界与 judge prompt 现状一致；16K 预算截断限制注入体量；叙事产物仅人读不驱动动作，无自动执行面。

## 涉及文件（Deliverables 依据）

- `core/adjudication_narrative.py`（采集器注册表、四段 prompt、异步生成、熔断器）
- `core/pm_engine/family.py`（发射点异步化改接线 + facts 参数位）
- `core/worktree_manager/mergeback.py`、`core/agent_runner/token_budget.py`（旁路点同接线）
- `core/dashboard/data/admin_alerts.py` 或读侧合并层（侧车合并，按实际读侧模块落位）
- `core/admin_store.py`（清理路径侧车级联）
- `.fenix/config.template.yaml`（叙事配置段注释随超时缺省同步）
- `docs/help/06-governance.md`（告警叙事说明更新）
- `core/dashboard/static/src/components/alert-shared.tsx`（占位 + 渲染确认）
- `core/dashboard/static/dist/index.html`（构建产物，reference）
- `tests/test_adjudication_narrative.py`（扩展）+ `tests/test_narrative_sidecar.py`（新增，按需）
