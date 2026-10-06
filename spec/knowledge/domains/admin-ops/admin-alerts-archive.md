# 处置/告警记录裁剪归档

<!-- knowledge: capability=admin-alerts-archive rev=1
     sources=spec/archive/2026-10-07-add-alerts-archive-and-overview-cache -->

AdminStore 活跃告警池的滚动历史留痕：超限被裁出的处置/告警记录追加进 JSONL 归档文件而非丢弃，并经只读 API 出口可查，运维审计链不断裂。

## 规则

- 活跃池上限 `MAX_RECORDS=150`：`AdminStore` 写回前自动裁剪到最近 150 条（新记录在数组末尾，删头部最旧的）。
- 裁剪即归档：被裁剪移出的每条记录按行追加写入 `<project_root>/.fenix/admin_alerts_archive.jsonl`（UTF-8，每行一条完整 JSON 记录，内容与活跃池中逐字段一致；写入顺序即裁剪顺序即时间正序）。归档追加与裁剪在同一把排他锁内完成，不丢记录。
- 归档软失败：归档写失败（磁盘满/权限等）仅记日志不抛异常，活跃文件写回主路径照常完成，永不被归档拖挂。
- 归档滚动上限 `MAX_ARCHIVE_RECORDS=2000`：归档文件超过 2000 条时裁掉最旧记录回到上限内（裁剪在归档追加后同锁执行，整文件重写走临时文件 + rename）；归档上限独立于活跃上限，最旧历史按序永久淘汰。
- 缺省读路径不含归档：`get_admin_activities` 与 `/api/admin-activities` 缺省只读活跃 `admin_alerts.json`（150 条池），归档数据不进入任何缺省读路径。
- 归档只读出口：`/api/admin-activities` 支持 `archived=1` 返回归档记录，响应体为 `{"archived": true, "total": N, "page": P, "page_size": M, "has_more": B, "activities": [...]}`，支持与活跃路径一致的 `page`/`page_size` 分页，按时间倒序。
- 归档聚合口径与活跃缺省聚合同口径：缺省（无 `?project=`）聚合全部非 fixture 项目的归档并逐条注入 `project` 字段；`?project=` 限定单项目；`archived=1` 与 `?spec=` 可组合（先 spec 过滤后分页）。
- 归档文件与活跃文件同目录（`.fenix/`），同属运行时数据不进 git；归档消费出口仅此 API，无前端归档浏览界面。

## 关键行为

- 活跃文件已有 150 条再写入 1 条新记录：最旧 1 条从活跃文件移出并出现在归档文件末行，活跃文件仍为 150 条。
- 归档文件已达 2000 条再发生一次裁剪归档：新条目落末尾，最旧 1 条被淘汰，归档保持 2000 条。
- 归档文件不可写时发生裁剪写回：活跃文件写回成功（150 条），日志记录归档失败，无异常抛出。

## 溯源

- 2026-10-07 add-alerts-archive-and-overview-cache（spec/archive/2026-10-07-add-alerts-archive-and-overview-cache） — 新增裁剪归档能力：JSONL 旁路追加归档、2000 条滚动上限、写失败软失败、缺省读路径不变、`?archived=1` 分页只读出口
