# 设计

## 现状与断点

- core/knowledge.py L1445 `check_retry_ledger_age`：只看 todo.md 未勾选行 + 24h 龄期，不看产物、不看 pending.json。
- L1289 `_register_todo_retry`：登记只写不闭；recommended_action 明言人工勾选。
- L1397/L1477 `_STALE_RETRY_REMINDED_ON`：进程内标记，重启即失效（11-14 四次重启四条重复告警实测）。

## 方案

### 产物存在性核验

- 在 stale 判定后增加 `_artifact_landed_since(name, since)`：`git log --format=%H:%ct:%s` 遍历（`-i --grep=knowledge: distill` 预过滤 + spec 名匹配），取最早一个提交时刻 >= since 的命中。since 取该行所属日期节日期零点（台账登记以日期节承载，行内无时刻；按日期零点起算对「落库早于当日登记但晚于零点」的行同样闭合——该行登记时产物已在历史中，本属假欠账，闭合方向正确）。名字命中须带定界约定：主题中名字之后须为行尾或 `,`（模板定界符），防行名恰为另一 spec 名前缀时被其产物提交误闭合（如登记 `fix-x` 而历史仅有 `fix-x-2` 产物提交）。
- 提交主题实况为 `[fenix] knowledge: distill <name>`（9d5f616b9 实测吻合；多名形态以 `, ` 连接，与子串预过滤兼容）；主题漂移时核验 miss，退化为现行为（仍催办），无回归风险。
- git 不可用（非仓库/命令失败）：记 debug 日志、跳过核验，行为与现状一致。

### 自动勾选回写

- 按 `_stale_distill_retry_lines` 解析所得**行文本**精确定位（该原语返回 `(行文本, 登记日期)`，不含行号；行文本唯一——登记侧按整行文本精确包含幂等），`[ ]` → `[x]` 原地替换；写回复用 `append_todo_line` 同款 tmp+os.replace + flock 串行原语，与回填车道并发安全（防并发截断重演 1bb1eacf2463）；重复执行（行已勾选）自然跳过，幂等。
- 上线后首轮检查点即自动闭合现存两条 11-09 假欠账行，无需人工清账（对应原条目建议第三段）。

### 去重持久化

- 新增 .fenix/ 状态文件（与 knowledge_audit_state.json 同形态的原子写 json），键：`last_reminded_date` + `last_stale_fingerprint`（当日 stale 行集合的稳定指纹）。检查点发出催办前：同日且指纹未变则跳过；跨日或指纹变化（新增欠账）则放行并更新。daemon 重启读盘恢复，不再依赖模块属性。

## 测试

- tests/test_knowledge_distill_resume.py（既有 check_retry_ledger_age 用例群 L673-720 处扩展）：产物提交晚于登记即闭合不催办、同日内分钟级间隔可闭合、产物不存在仍催办、git 异常 fail-open、状态文件已含当日则重启后不重发、指纹变化（新欠账）同日放行。