## Deliverables

```yaml
- path: core/admin_store.py
  kind: modify
- path: core/dashboard/data/admin_alerts.py
  kind: modify
- path: core/dashboard/routes/alert_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: tests/test_admin_store_archive.py
  kind: new
- path: tests/test_dashboard_api.py
  kind: modify
```

## 1. 归档写入（存储层）

- [ ] 1.1 `core/admin_store.py` 新增归档常量 `ARCHIVE_NAME = "admin_alerts_archive.jsonl"` 与 `MAX_ARCHIVE_RECORDS = 2000`；裁剪路径（超过 `MAX_RECORDS` 删头部）把被移出记录逐行追加写入 `<project_root>/.fenix/admin_alerts_archive.jsonl`，与裁剪同锁完成；归档写失败仅记日志不抛出、不阻塞活跃文件写回
- [ ] 1.2 归档追加后执行归档自身滚动裁剪：记录数超 `MAX_ARCHIVE_RECORDS` 时保留末尾 2000 行（整文件重写，同锁内）
- [ ] 1.3 新建 `tests/test_admin_store_archive.py`：151 条写回触发 1 条归档（内容逐字段一致、活跃仍 150 条）、归档不可写时活跃写回成功且无异常、2001 条归档触发滚动淘汰（最旧出、最新留）

## 2. 归档读出口（数据层 + 路由）

- [ ] 2.1 `core/dashboard/data/admin_alerts.py` 新增 `get_archived_activities(project_root, spec=None) -> list`：逐行读归档 JSONL（容错跳过损坏行），可选 spec 过滤，返回时间倒序列表（不与活跃文件合并）
- [ ] 2.2 `routes/alert_routes.py` `_api_admin_activities` 支持 `archived=1`：响应体 `{"archived": true, "total", "page", "page_size", "has_more", "activities"}`，支持 `page`/`page_size` 分页（默认 50 上限 200）与 `?spec=`/`?project=` 组合；缺省（不带 archived）响应零变化
- [ ] 2.3 `tests/test_dashboard_api.py` 新增用例：`archived=1` 分页切片语义、`archived=1&spec=X` 组合过滤、损坏 JSONL 行被跳过、缺省请求响应与归档功能上线前一致

## 3. overview 结果缓存（路由层）

- [ ] 3.1 `routes/base.py` overview handler 加单槽缓存 `{sig, projects_key, computed_at, payload}` + `threading.Lock`：TTL 2s 内直接命中；超 TTL 但「项目集合 + 全部项目数据源签名」未变时复用；任一键变化重算聚合并更新缓存；签名用 `(path, mtime_ns, size)` 失效键模式（若 `add-dashboard-paging-and-etag` 已落地 `core/dashboard/data/signature.py` 则复用其函数，否则本任务内联最小实现并留注释待归一）
- [ ] 3.2 `tests/test_dashboard_api.py` 新增用例：2s 内 3 连请求仅首次聚合（第 2/3 次 ≤5ms 且内容一致）、超 TTL 签名未变复用、STATE.md 变化后重算反映新状态、项目注册/移除后缓存失效

## 4. 回归

- [ ] 4.1 后端全量测试通过：`python3 -m pytest tests/test_admin_store_archive.py tests/test_admin_store_corruption.py tests/test_dashboard_api.py tests/test_dashboard_index.py -x -q`
- [ ] 4.2 存量回归确认：运维页时间线展示内容与改造前一致（同 fixture 数据逐条对比）、`get_admin_activities` 全部既有调用方（横幅/弹窗）无行为变化
