# 蒸馏重试台账自动闭环与催办去重

## 背景

knowledge-distill（知识归档蒸馏）失败时在项目 todo.md 登记 `[ ] knowledge-distill 重试：归档 <spec 名>` 待重试行。核查证实（2026-11-15 复核 run）：台账存在两类已发生的系统性缺陷——

1. **假欠账无自动闭合**：产物 commit 9d5f616b9（`[fenix] knowledge: distill add-systemd-hosting`，2026-11-05T04:25:06+08:00）已落库，但其重试台账行（登记 2026-11-04）无人勾选，欠账告警在落库后 17/20 小时仍复燃两次（todo.md 复核条目「distill重试台账成功不清账」在档互证）。代码根因：core/knowledge.py `check_retry_ledger_age`（L1445）判定催办前不检索产物是否已存在；`_register_todo_retry`（L1289）只写不闭，全框架无任何自动勾选路径（core/ 内台账行唯一写入点即登记），闭合只有人工一条路。
2. **催办去重被重启击穿**：同日至多一条的幂等标记 `_STALE_RETRY_REMINDED_ON`（L1397/L1477）是进程内模块属性，daemon 重启即丢失。11-14 四次优雅重启对应四条重复告警，信号 knowledge_distill_retry_stale 自 11-10 起累计 32 条全部 handled=false，纯告警噪音与检查点 token 消耗。

## 目标

- 催办信号发出前对每条 stale 重试行做产物存在性核验：项目 git 历史中存在提交主题含 `knowledge: distill` 且含该行 spec 名、且提交时刻晚于该行登记时刻（时刻级比较）的提交，即判定产物已落库——跳过催办并回写 todo 勾选，实现自动闭环。
- 幂等去重标记持久化到磁盘，daemon 重启后当日不重发催办。
- 上线时若存在存量假欠账行（登记日期节早于产物落库时刻的未勾选行），由下一次检查点自动闭合，无需人工清账（spec-review 2026-11-16 复核：当前主树 .fenix/todo.md 已无存量台账行，本目标对存量行自然空转；机制面仍须覆盖后续新登记行的自动闭环）。

## 范围外

- 不改蒸馏触发与重试队列（knowledge-distill-pending.json）语义。
- 不改 admin_alerts 告警通道本身的存储与生命周期。
- 不自动重试蒸馏（仍由既有重试机制消费 pending 队列）。