# 立项请求（原话照录）

> 用户（2026-11-09 19:24，消息 m00508，对 lead 报告的批复）：「立项，full，立即执行」

立项对象（lead 报告 m00507 中列出的 arbiter 缺口 ①+②，用户已批准）：

1. **缺口① dead-man 不分故障类型**：arbiter 裁决车道的基础设施秒挂（CLI 缺失、凭据缺失、bundle 不兼容——特征是 0 rounds、无任何 API 往返）与真实判断失败走同一连败计数，达到 `max_consecutive_failures` 后一律签发台账 kind=dead-man；dead-man「跨重启永久单次例外不复位」且**无任何解除 API**（代码只有 `_ledger_sigs` 读、无清）。实证：2026-11-09 本地 09:01–09:08 四个签名（m3/gaming/p2p::spec-review-incomplete + single-app::redispatch_loop_detected，见 .fenix/arbiter_ledger.jsonl）全部 failed→dead-man→chain-escalated、arbiter_rulings=0；config 17:07:35 修好显式模型链后（17:29 车道已能正常产裁决包），上午四个签名依然永久人工——基础设施故障被固化成永久人工处置。
2. **缺口② 车道无启动/前置自检**：arbiter/repair 车道的 CLI 与凭据可用性没有任何启动探测——车道 09:00 起挂死，直到阻塞堆积才发现（挂了约 8 小时无人知晓）。对照面：推送凭证自检已在 SPEC fix-push-credential-env-and-retry-rearm 立项（针对 git 凭据面）；本 SPEC 覆盖 agent 裁决车道的同类自检缺口。

## 明确不在本 SPEC 范围

- 缺口③（升级件自环回派）不在本 SPEC：arbiter 已自行记入 todo（p2p::impl_budget_exhausted 裁决包 gap-noted 2026-11-09 17:29）。
- 推送/git 凭据面自检：已由 fix-push-credential-env-and-retry-rearm 承接，不重复。
- dead-man 对「真实判断失败」（有 API 往返、分析未收敛或裁决被否）的永久语义**保持不变**——只新增基础设施故障的分级与复位通道。
