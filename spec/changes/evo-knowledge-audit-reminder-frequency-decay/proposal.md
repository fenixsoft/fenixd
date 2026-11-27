# 提案：知识体检聚合提醒超期降频节拍

## 背景

知识真相源体检（core/knowledge_audit.py）对 spec/knowledge 的规则冲突与过期项产出 escalated 疑点，等待人工在 .fenix/knowledge_audit_arbitration.json 按 fingerprint/decision/decided_at/note 登记仲裁，框架检查点（daemon 300s 知识维护检查点：fenixd.py:1929-1931 调 knowledge_daily_check，后者 core/knowledge_audit.py:934 调 consume_arbitration）当日自动消费。框架侧同时每日生成一拍聚合提醒（todo 聚合行原位替换+提交落库），提醒无响应即无限每日重复。

实测：13 条 escalated 疑点最长积压 53 天（first_seen 2026-09-30）、仲裁文件从未创建，聚合提醒自 2026-10-04 首拍起已 38 拍零消费——每日一拍 git 提交噪音持续约 7 周，且积压期间仍有新增升级（10 条→13 条）。「同指纹超 7 天未消费降为每周一拍」的提醒面改造建议已连续四窗（11-19 至 11-22）登记未承接。

## 目标

对持续零仲裁消费的超龄 escalated 聚合提醒降频为每周一拍，消除**该聚合提醒的**每日提交噪音（.fenix/todo.md 同前缀聚合行逐日提交）；欠账信号不丢失——disputed 注记仍常驻知识页、todo 聚合行仍在、任一指纹被消费后恢复每日节拍。

## 非目标

- 不改变仲裁人工登记语义与消费检查点行为；不引入自动仲裁；disputed 注记逻辑不动。
- 不改 run_audit 每轮对 spec/knowledge/log.md 的「audit 体检留痕」lint 行及其每日提交（core/knowledge_audit.py:2573-2590，独立于聚合提醒节拍）；本 SPEC 只消除 todo 聚合行的逐日提交，不等价于「知识域所有每日提交归零」。
- 不改变 escalated 升级判据与 findings 台账结构。
- 根治手段仍是人工一次性登记 13 条指纹（框架当日消费后提醒自然止拍）。

## 实现前置

同域已有 SPEC `evo-add-knowledge-audit-reminder-downfreq`（spec/changes/evo-add-knowledge-audit-reminder-downfreq，当前同为 reviewing）覆盖同一提醒链与同一每日提交噪音。两者门控位置与状态键名不同，并行实现会形成双重门控、互相覆盖状态键。实现前 MUST 择一保留并归档其余；建议保留本 SPEC（它显式区分超龄阈值与消费后恢复节拍），另一归档。
