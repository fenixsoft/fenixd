# ADR-359：不可达申报感知通道与顶层 status 解耦、感知面与放行面分离

date: 2026-11-16
status: accepted

## Context

不可达申报（unattainable）的人工感知通道曾全部以结果文件顶层 `status: "partial"` 为前提：车道告警消费点与 verified→done 门禁消费点均只认 partial。fast-track 顶层合同唯一合法顶层值为 success（verified/bug-found 属于 verification.verdict），`success + unattainable` 因此是合法申报形态，却在全部消费点静默——实现者如实申报任务缺口，SPEC 正常推进到 verified，全程零告警，缺口滞留只能靠人工主动查进度发现（fix-spawn-attribution-hardening 事故，2026-11-16）。诚实退出的存在意义是「做不完要如实上报」，申报在上报成功的那一刻静默丢失，使该机制的核心承诺失效。

## Decision

申报的人工感知通道触发条件为「申报存在且全部条目合法」，与结果文件顶层 status 取值无关。两车道（full / fast-track）成功收口路径各设一个申报告警写入点，与 partial 收敛分支互斥不重复告警；告警复用唯一出口 `_note_unattainable_todos`（signal_type / severity / 消费出口不变），禁另立平行信号；申报解析复用单点薄封装（`declared_unattainable`），禁第二解析点。success 路径告警 MUST 传拦截语境文案——该形态下门禁不放行，「门禁已放行」文案失实。感知面与放行面永久分离：告警与注记只改变人工感知，不改变任何门禁放行语义，success+unattainable 仍被 verified→done 门禁 fail-closed 拦截，人工裁决出口（补勾 / 回炉 / 诚实退出豁免）不变。

## Consequences

- 后续新增申报消费点禁止以特定顶层收工形态为前提；新感知通道必须接入同一告警出口，申报解析必须走同一单点。
- 「感知不驱动放行」成为永久约束：告警语义不得反向改写门禁判定，门禁兜底（本事故中唯一兜底）不因告警在场而弱化。
- 两个零变化边界须由车道对称测试锚定：无申报路径零误报（申报缺失/为空不告警）、非法申报 fail-closed（整体不生效，不部分采信）。
- 代价：success+unattainable 形态下 SPEC 必然停在 verified→done 等人工裁决（这是设计内的兜底而非缺陷）；感知粒度到「已申报不可达」计数，明细靠告警证据与结果文件。
