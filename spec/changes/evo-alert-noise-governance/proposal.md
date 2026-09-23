# alert-noise-governance — 告警噪音治理：源头分类、消费端过滤与升级降敏

## Why

夹具项目（scheduling-showcase）的验证留痕与真实记账同住 STATE.md、admin_alerts.json 与 runs/，09-22 实证出一条完整的噪音链：

1. **闸门误分类（源头）**：已交付 spec（c-sched-set，实现已合并 f581cf7/18cc408/db252d1、验证 25/25 通过）被外部 STATE 重置打回 ready 后，内容完整性闸门按「空 spec」冻结并挂 major 告警——处置方向与事实相反，至今未纠正（gate-delivered-spec-exemption 登记链）；
2. **重放不断链（中程）**：冻结 spec 被外部回置 ready 后，恢复路径与派发链均不复核 frozen，同日重放 9 轮「就绪→派发→拦截→冻结」，全天 18 条闸门 ERROR（frozen-replay-escalation-guard 登记链）；
3. **升级无降敏（出口）**：闸门 ERROR 指纹直达 daemon_errors 升级条件（≥2 次/10 分钟、间隔 ≤5 分钟），同轮孪生指纹各算各的，点燃 3 笔 Administrator 召唤（admin-global-1790077896/1790079806/1790080340，其一 45 轮后被停机截断、产出归零记账失败 run）；
4. **消费端不识别夹具**：日审 _collect_admin_summary 直读告警 store，把夹具告警计入未处理计数；admin_monitor 召唤决策不读 fixture 标记，夹具项目内照常召唤（fixture-noise-channel-isolation 登记链）。

fix-fixture-project-alert-noise 已落地项目级 fixture 标记（dashboard.yaml 项目条目，core/dashboard/registry.py）、看板聚合过滤与 --reset 基线复位，但上述四个环节均未接入治理。三支前序草稿（fixture-noise-channel-isolation / frozen-replay-escalation-guard / gate-delivered-spec-exemption）各治一段且互留非目标，本 SPEC 合并三者为同一条治理线：源头分类、断重放、降敏、消费端过滤一次闭合。

## What Changes

- **A｜闸门源头分类修正**（原 gate-delivered-spec-exemption）：终态（done/archived）短路——不冻结不出 spec_content_missing；「无认可内容但存在 verification-report.md」改产 spec_delivered_no_content 独立信号（不冻结、文案引导人工裁决），并接入 alert_lifecycle 自动闭环；spec_has_content 派发判据不动。
- **B｜恢复/派发链 frozen 复核**（原 frozen-replay-escalation-guard ①）：_recover_ready 与 _on_spec_ready 守卫链加 frozen 早退（INFO 留痕），冻结 spec 不再被孤儿恢复或重启回放送进派发。
- **C｜daemon_errors 升级降敏**（原 frozen-replay-escalation-guard ②）：指纹级「重启后首扫」冷却窗 + 同轮孪生指纹合并为一条召唤信号。
- **D｜日审读侧过滤**（原 fixture-noise-channel-isolation ①）：_collect_admin_summary 识别 fixture 标记项目，夹具告警不进未处理计数、以 fixture 标注单独呈现。
- **E｜召唤通道 fixture 抑制**（原 fixture-noise-channel-isolation ②）：admin_monitor 自动召唤决策点对 fixture 标记项目抑制（INFO 留痕），人工显式触发不受限。

**BREAKING**：无。全部为新增早退/分支/过滤与阈值行为；既有拦截语义、派发行为、告警记录本身保持。

## 非目标

- 不改 spec_has_content 四选一派发内容判据（verification-report.md MUST NOT 进认可名单——对 STATE 被外部重置为 ready 的已交付 spec，放进判据会触发盲目重实现，09-12 实证）；
- 不改闸门拦截语义与「人工补内容解冻」契约本体，不改 StateMachine 的 frozen 剥离保护；
- 不改看板聚合过滤与 --reset 基线复位（fix-fixture-project-alert-noise 已覆盖）；
- 不删除/不改写夹具告警记录本身（看板仍可见）；
- 不强制验证场景迁移临时 project_root、不改交付链落盘行为（属后续迭代）；
- 不做 c-sched-set/c-sched-clear 的人工裁决本身（人工步骤：按已交付裁决补 tasks.md 后解冻，或写处置记录说明预期空 spec）；
- 不改 _diff_specs 的 status diff 机制本体（回放断链由消费端 frozen 复核承担，避免事件层过滤吞掉人工 kick 等合法路径）。

## 验收

- done/archived 态 spec 目录为空：闸门不冻结、无 spec_content_missing、状态保持终态；目录仅含 verification-report.md：产 spec_delivered_no_content 且不冻结，人工裁决后告警自动闭环；
- frozen=True 的 spec 不被孤儿恢复清 error/重派（INFO 留痕、零 STATE 写入），重启回放经 _on_spec_ready 跳过派发，闸门 ERROR 不再产生；
- 重启后首扫回放的已知指纹在冷却窗内不召唤 Administrator；同轮成对指纹只产一条召唤信号；窗后复现或全新指纹照常升级；
- fixture:true 项目的告警不进日审未处理计数（带标注单独呈现）；其同源 ERROR 达升级条件不再自动召唤（INFO 留痕）；非夹具项目日审摘要与召唤行为与现状完全一致。
