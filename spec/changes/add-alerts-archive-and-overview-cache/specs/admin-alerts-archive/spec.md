## ADDED Requirements

### Requirement: 裁剪时归档

`AdminStore` 写回裁剪（记录数超过 `MAX_RECORDS=150` 删头部最旧）时，被移出的每条记录按行追加写入 `<project_root>/.fenix/admin_alerts_archive.jsonl`（UTF-8，每行一条完整 JSON 记录，写入顺序即裁剪顺序即时间正序）。归档写入与裁剪在同一把锁内完成，失败不阻塞主写回（归档写失败仅记日志，活跃文件照常落盘）。

#### Scenario: 超限裁剪触发归档

- **WHEN** 活跃文件已有 150 条，再写入 1 条新记录
- **THEN** 最旧 1 条从活跃文件移出并出现在归档文件末行（内容逐字段一致），活跃文件仍为 150 条

#### Scenario: 归档失败不阻塞主写回

- **WHEN** 归档文件不可写（权限/磁盘）时发生裁剪写回
- **THEN** 活跃文件写回成功（150 条），日志记录归档失败，无异常抛出

### Requirement: 归档文件滚动上限

归档文件记录数超过 `MAX_ARCHIVE_RECORDS`（默认 2000）时，裁掉最旧记录使文件回到上限内（裁剪在归档追加后同锁执行）。归档上限独立于活跃上限，耗尽后最旧历史按序永久淘汰。

#### Scenario: 归档自身滚动淘汰

- **WHEN** 归档文件已达 2000 条，再发生一次裁剪归档（追加 1 条）
- **THEN** 归档文件裁至 2000 条：新条目在末尾，最旧 1 条被淘汰

### Requirement: 读侧时间线语义不变

`get_admin_activities` 与 `/api/admin-activities` 缺省行为不变：只读活跃 `admin_alerts.json`（150 条池），时间线展示与归档功能上线前逐条一致。归档数据不进入任何缺省读路径。

#### Scenario: 缺省响应与归档无关

- **WHEN** 归档文件已累积 500 条后请求 `/api/admin-activities`（不带 archived 参数）
- **THEN** 响应内容与归档功能上线前同条件请求完全一致

### Requirement: 归档只读出口

`/api/admin-activities` 支持 `archived=1` 参数：返回归档记录（支持与活跃路径一致的 `page`/`page_size` 分页语义，按时间倒序），响应体为 `{"archived": true, "total": N, "page": P, "page_size": M, "activities": [...]}`。`archived=1` 与 `?spec=` 可组合（先 spec 过滤后分页）。

#### Scenario: 归档分页读取

- **WHEN** 归档含 120 条，请求 `archived=1&page=2&page_size=50`
- **THEN** 返回时间正序的第 51–100 条倒序排列（即最新方向第 51–100 条），`total=120`，`has_more=true`

#### Scenario: 归档与 spec 过滤组合

- **WHEN** 请求 `archived=1&spec=X&project=P`
- **THEN** 仅返回项目 P 归档中 spec=X 的记录
