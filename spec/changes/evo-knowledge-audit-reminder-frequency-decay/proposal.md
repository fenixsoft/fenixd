## 背景

知识真相源体检（core/knowledge_audit.py）对 spec/knowledge 的规则冲突与过期项产出 escalated 疑点，等待人工在 .fenix/knowledge_audit_arbitration.json 按 fingerprint/decision/decided_at/note 登记仲裁，框架检查点（daemon 300s 检查点，fenixd.py:1822-1824 调 consume_arbitration）当日自动消费。框架侧同时每日生成一拍聚合提醒（todo 聚合行原位替换+提交落库），提醒无响应即无限每日重复。

实测：13 条 escalated 疑点最长积压 53 天（first_seen 2026-09-30）、仲裁文件从未创建，聚合提醒自 2026-10-04 首拍起已 38 拍零消费——每日一拍 git 提交噪音持续约 7 周，且积压期间仍有新增升级（10 条→13 条）。「同指纹超 7 天未消费降为每周一拍」的提醒面改造建议已连续四窗（11-19 至 11-22）登记未承接。

## 目标

对持续零仲裁消费的超龄 escalated 聚合提醒降频为每周一拍，消除每日提交噪音；欠账信号不丢失——disputed 注记仍常驻知识页、todo 聚合行仍在、任一指纹被消费后恢复每日节拍。

## 非目标

不改变仲裁人工登记语义与消费检查点行为；不引入自动仲裁；disputed 注记逻辑不动。根治手段仍是人工一次性登记 13 条指纹（框架当日消费后提醒自然止拍）。