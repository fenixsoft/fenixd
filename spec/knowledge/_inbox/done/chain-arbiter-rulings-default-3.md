# 处置链 Arbiter 复现配额缺省 2→3

## 背景

2026-11-03 首例事件中该签名两轮裁决均「三重白名单外」（配置读取与链账本见
`escalation-chain-orphan-watchdog-double-path.md`），配额 2/2 烧尽即强制上升
人工。用户定调：第二次裁决仍白名单外时留第三次自主处置机会，不提前落人工。

## 结论（当前事实）

- 处置链 Arbiter 复现配额缺省为 **3 次/签名**（第 4 次复现强制上升人工）：
  单源 `ConfigLoader.CHAIN_ARBITER_RULINGS_DEFAULT = 3`；两处运行时兜底
  （`arbiter.py _arbiter_rulings_quota`、`escalation_chain.py quota_config`
  except 字典）与 Dashboard ChainPanel `CHAIN_DEFAULTS` 同值对齐。
- Admin 尝试配额仍为 2/签名，复位窗仍 7 天或 spec 状态迁移清零，均未变。
- 配额语义不变：Arbiter 拍板成功即闭环（不计「复现」）；连续复现才逐次烧
  拍板配额。本变更只放宽自动化兜底深度，不改变链序与人工出口语义。

## 证据

- `core/config.py` CHAIN_ARBITER_RULINGS_DEFAULT=3（2026-11-03 交互会话改，
  用户指令「将 arbiter 的拯救轮次默认配额从 2 调整到 3」）
- 首例事件时间轴与两轮裁决全文：见同目录
  `escalation-chain-orphan-watchdog-double-path.md` 及
  `.fenix/arbiter_ledger.jsonl` arb-ledger-1793705465700（ruling1）/ 21:25 波
  （ruling2，配额烧尽后链强制上升人工）
- 折叠落点建议：admin-ops/escalation-chain.md「Arbiter 链上语义」段配额句与
  spec/changes/add-escalation-chain-admin-arbiter/specs/escalation-chain/
  spec.md「Arbiter 拍板与复现配额」需求的「复现配额 2 次/签名」表述需随本条
  更新为「缺省 3 次/签名（第 4 次复现强制上升人工）」。
