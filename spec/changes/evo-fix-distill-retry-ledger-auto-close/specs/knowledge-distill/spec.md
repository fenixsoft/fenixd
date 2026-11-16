# 能力：knowledge-distill（知识归档蒸馏）

## 既有行为

- 蒸馏 run 失败时 `_register_todo_retry`（core/knowledge.py L1289）向项目 todo.md 写入未勾选重试行（fail-open）。
- 检查点 `check_retry_ledger_age`（core/knowledge.py L1445，fenixd.py L1770 每 300s 调用）解析 todo.md 未勾选重试行，行所属日期节零点起算超过 RETRY_STALE_AFTER（24h，L1389）即发 knowledge_distill_retry_stale 告警。
- 同日至多一条的幂等依赖进程内模块属性 `_STALE_RETRY_REMINDED_ON`（L1397/L1477）。

## 本 SPEC 新增行为

1. **产物存在性核验（自动闭环）**：`check_retry_ledger_age` 在判定某行 stale 后、发告警前，按该行 spec 名在项目 git 历史检索产物提交（提交主题匹配 `knowledge: distill` 且含该 spec 名；名字命中须为模板定界位置——主题中名字之后为行尾或 `,`，防前缀互含误闭合）。存在且提交时刻晚于该行登记时刻（取该行所属日期节日期 + 行内无时刻时的保守处理，比较粒度到秒）即判定产物已落库：跳过催办，并将该行回写为已勾选（`[ ]` → `[x]`）。回写幂等可重入。
2. **去重持久化**：`_STALE_RETRY_REMINDED_ON` 迁移为磁盘状态（.fenix/ 下状态文件，记录当日已发日期），daemon 重启后同日不重发催办；跨日自然重置。
3. **失败开放**：核验过程异常（非 git 仓库、git 命令失败、todo.md 解析失败）保持现行为——仍催办、不勾选，不阻塞检查点。

## 验收

- 产物提交晚于登记（含同日内分钟级间隔，如本例 41 分钟）的行被自动勾选且不产生催办。
- 产物不存在的 stale 行仍照常催办。
- daemon 重启后同日不重复发催办（磁盘状态生效）。
- 非 git 目录下行为与现状一致（回归不破）。