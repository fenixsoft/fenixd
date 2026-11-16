# 设计

## 现状与断点

- core/knowledge.py L1445 `check_retry_ledger_age`：只看 todo.md 未勾选行 + 24h 龄期，不看产物、不看 pending.json。
- L1289 `_register_todo_retry`：登记只写不闭；recommended_action 明言人工勾选。
- L1397/L1477 `_STALE_RETRY_REMINDED_ON`：进程内标记，重启即失效（11-14 四次重启四条重复告警实测）。

## 方案

### 产物存在性核验

- 在 stale 判定后增加 `_artifact_landed_since(name, since)`：`git log --format=%H:%ct:%s` 遍历（`-i --grep=knowledge: distill` 预过滤 + spec 名子串匹配），取最早一个提交时刻 >= since 的命中。since 取该行所属日期节日期零点（台账登记以日期节承载，行内无时刻；时刻级秒比较保证同日内「登记 02:02Z → 落库 02:43Z」能闭合——本例即依赖秒级粒度）。
- 提交主题模板 `knowledge: distill <name-a>, <name-b>` 以固定模板为匹配基础（291fb59 实测吻合）；模板漂移时核验 miss，退化为现行为（仍催办），无回归风险。
- git 不可用（非仓库/命令失败）：记 debug 日志、跳过核验，行为与现状一致。

### 自动勾选回写

- 复用既有 todo.md 行级写回原语（`_stale_distill_retry_lines` 解析所得行号），`[ ]` → `[x]` 原地替换，写入前整读整写防并发截断；重复执行（行已勾选）自然跳过，幂等。
- 上线后首轮检查点即自动闭合现存两条 11-09 假欠账行，无需人工清账（对应原条目建议第三段）。

### 去重持久化

- 新增 .fenix/ 状态文件（与 knowledge_audit_state.json 同形态的原子写 json），键：`last_reminded_date` + `last_stale_fingerprint`（当日 stale 行集合的稳定指纹）。检查点发出催办前：同日且指纹未变则跳过；跨日或指纹变化（新增欠账）则放行并更新。daemon 重启读盘恢复，不再依赖模块属性。

## 测试

- tests/test_knowledge_distill_resume.py（既有 check_retry_ledger_age 用例群 L673-720 处扩展）：产物提交晚于登记即闭合不催办、同日内分钟级间隔可闭合、产物不存在仍催办、git 异常 fail-open、状态文件已含当日则重启后不重发、指纹变化（新欠账）同日放行。