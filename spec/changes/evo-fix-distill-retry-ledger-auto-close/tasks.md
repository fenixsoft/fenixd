## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: tests/test_knowledge_distill_resume.py
  kind: modify
```

## 1. 产物存在性核验与自动闭环

- [x] 1.1 core/knowledge.py check_retry_ledger_age（L1445 附近）：stale 判定后、发催办前按行内 spec 名检索项目 git 历史（提交主题含 `knowledge: distill` 与该 spec 名——名字命中须带定界约定：名后为行尾或 `,`，防前缀互含误闭合；提交时刻晚于该行所属日期节零点，比较粒度到秒），命中即判定产物已落库并跳过催办
- [x] 1.2 core/knowledge.py：对已判定产物落库的行按 `_stale_distill_retry_lines` 所得行文本精确定位 todo.md 对应行，`[ ]` 原地回写为 `[x]`（复用 append_todo_line 同款 tmp+os.replace+flock 原语、幂等可重入）；git 不可用或核验异常时保持现行为仍催办，不阻塞检查点

## 2. 催办去重持久化

- [x] 2.1 core/knowledge.py：把同日至多一条的幂等标记 `_STALE_RETRY_REMINDED_ON`（L1397/L1477 进程内模块属性）迁移为磁盘持久状态（.fenix/ 下原子写状态文件，记录当日已发日期与 stale 集合指纹），daemon 重启后同日不重发；跨日或指纹变化（新增欠账行）时放行

## 3. 测试

- [x] 3.1 tests/test_knowledge_distill_resume.py：在既有 check_retry_ledger_age 用例群（L673-720）处扩展——产物提交晚于登记即闭合且不催办、同日内分钟级间隔（登记与落库差数十分钟）可闭合、产物不存在仍催办、git 命令失败 fail-open 仍催办、行名是另一 spec 名前缀（历史仅存在更长名产物提交）时不得误闭合仍催办、状态文件含当日时重启后不重发、当日新增欠账行（指纹变化）放行