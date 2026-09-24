## Deliverables

```yaml
- path: core/dashboard/registry.py
  kind: modify
- path: core/dashboard/routes/alert_routes.py
  kind: modify
- path: bin/fixture_scheduling_showcase.py
  kind: modify
- path: tests/test_fixture_project_governance.py
  kind: new
```

## 1. Registry 夹具标识字段

- [x] 1.1 `core/dashboard/registry.py`：读取层对旧配置（项目条目无 `fixture` 键）MUST 不报错。注意实测事实：`load()`（`registry.py:106-130`）只归一化顶层键（`port`/`projects`/`scan_dirs`/`ignored`），对 `projects` **条目原样透传**——不存在「条目默认结构」，故无缺键风险，**无需**在 `load()` 里补键或规范化条目（补键还会在后续 `save()` 时把 `fixture: false` 写进所有存量条目）。缺省假由消费点 `bool(p.get("fixture"))` 承担，非布尔值一并按假处理
- [x] 1.2 `discover()` 在构造显式 `projects` 结果的 dict 时增加 `"fixture": bool(p.get("fixture"))`；扫描发现（`scan_dirs` / 主目录一级子目录）产生的项目 dict 一律 `"fixture": False`（扫描无法判定夹具属性，缺省保守=非夹具）
- [x] 1.3 `Registry.add_project(path, name=None, fixture=False)` 新增 `fixture` 关键字参数：新条目写入 `{"name", "path", "fixture"}`；已存在同路径条目时保持既有「跳过」语义（不重复添加）。既有 `__init__`/`name` 位置参数调用方零改动
- [x] 1.4 新增 `Registry.mark_fixture(path, fixture=True)`（或等价更新方法）：按规范化路径定位配置条目并写入/更新 `fixture` 键后写回；目标路径不在配置中时返回未变更提示（不报错）。供夹具供给脚本对「已存在但缺标记」的条目补写

## 2. 夹具登记辅助

- [x] 2.1 `bin/fixture_scheduling_showcase.py` 的 `_ensure_registered()`：改为对 `Registry` 先尝试 `add_project(ROOT, fixture=True)`；若因条目已存在而跳过，则调用 1.4 的更新方法确保该条目 `fixture=True`（覆盖存量条目补标记场景）；任一步失败仍按既有约定仅 WARN 不阻断

## 3. 读侧跨项目聚合过滤

- [x] 3.1 `core/dashboard/routes/alert_routes.py` 的 `_api_alerts` 缺省（无 `project` 参数）分支：循环 `for p in self.server.projects():` 内增加 `if p.get("fixture"): continue`，使夹具项目的 `alerts`/`resolved`/`projects`/`total_unhandled` 均不参与聚合；显式 `?project=<name>` 分支 MUST NOT 改动
- [x] 3.2 `core/dashboard/routes/alert_routes.py` 的 `_api_admin_activities` 缺省分支：同样增加 `if p.get("fixture"): continue`，夹具项目不出现在 `projects` 数组；显式分支 MUST NOT 改动
- [x] 3.3 人工核对：`rg -n "for p in self.server.projects\(\)" core/dashboard/routes/` 列出全部缺省聚合点。实测共 **4** 处（非两处）：`alert_routes.py:45`（`_api_alerts` 缺省聚合）、`alert_routes.py:93`（`_api_admin_activities` 缺省聚合）、`alert_routes.py:134`（`_api_alerts_clear`——全项目「清理所有事件」的**写侧**动作）、`project_routes.py:24`（项目列表）。**仅前两处**属「告警/运维记录聚合读侧」适用面，仅它们加 `if p.get("fixture"): continue`
- [x] 3.4 `_api_alerts_clear`（`alert_routes.py:131-149`）MUST NOT 加夹具过滤：它是横幅「清理所有事件」按钮（前端 `POST /api/alerts/clear`）触发的写侧动作，过滤会让夹具 seed 告警无法被清理，并改变响应 `cleared` 计数语义。`project_routes.py:24`（项目列表）、`http_server.py` 的 `projects()` 缓存源（`server.py:410`/`http_server.py:95`）MUST NOT 加夹具过滤（夹具卡片与操作路径保持可见）

## 4. 夹具供给脚本复位告警基线

- [x] 4.1 `bin/fixture_scheduling_showcase.py` 的 `reset_fixture()`：在既有 `STATE.md`/`config.yaml` 写回之后，新增一步把 `ROOT/.fenix/admin_alerts.json` 复位为空数组基线（`[]`，UTF-8），使上一轮 seed 写入的告警/处置记录不跨轮累积。写入 MUST 为**原子写**（同目录 `tempfile.mkstemp` + `os.replace`，与 `AdminStore._write_unlocked`（`core/admin_store.py:136-155`）同形态），MUST NOT 裸 `write_text` 覆盖——夹具 `.fenix/` 内有常驻 daemon 与 seed 场景的并发读-改-写，半写文件会被 `AdminStore._read_unlocked`（`core/admin_store.py:69-101`）判为损坏并隔离改名，使后续 api 场景读到空集。MUST NOT 触碰 `admin_alerts.json.lock`（锁文件不属数据基线）；`.fenix/` 目录已由既有 `mkdir(parents=True, exist_ok=True)` 保证
- [x] 4.2 在 `--status` 分支（`show_status()`）输出中增加夹具 `admin_alerts.json` 的记录数（读取并计数，缺文件/损坏按 0），供人工只读核对复位效果

## 5. 测试

- [x] 5.1 新建 `tests/test_fixture_project_governance.py`：`discover()` 对显式 `fixture: true` 条目返回 `fixture=True`；对无 `fixture` 键的显式条目与扫描发现条目返回 `fixture=False`（用 `tmp_path` 构造 `dashboard.yaml` 与含 `.fenix/STATE.md` 的扫描根子目录）
- [x] 5.2 同文件：`add_project(path, fixture=True)` 写入的条目在 `discover()` 中 `fixture=True`；`mark_fixture` 对已有无标记条目补写 `fixture=True`、对不存在路径返回未变更
- [x] 5.3 同文件：构造两个项目（一个 `fixture: true` 带一条 `handled=false` major 升级告警，一个 `fixture: false` 带一条未处理告警），断言 `/api/alerts` 缺省响应不含夹具项目条目且 `total_unhandled` 不计入夹具告警、含非夹具告警；`?project=<夹具名>` 显式响应仍含该夹具告警全文（沿用 `tests/test_dashboard_api.py` 既有的 handler/临时项目装配夹具风格）
- [x] 5.4 同文件：断言 `/api/admin-activities` 缺省响应 `projects` 数组不含夹具项目；`?project=<夹具名>` 仍返回其处置记录
- [x] 5.5 同文件：临时夹具根（`tmp_path` + 假骨架）上调 `reset_fixture` 等价的告警复位逻辑，断言 seed 记录写入后经复位 `admin_alerts.json` 为空基线；连续两次复位仍有界（幂等）；对夹具路径 `add_project(fixture=True)` 后再执行登记辅助不产生重复条目且标记保持为真
- [x] 5.6 同文件：回归断言——`discover()` 对含 `fixture: true` 的项目仍返回在列表中（`fixture` 不改可见性）；`/api/projects/overview` 仍包含该夹具项目卡片

## 6. 验证与收尾

- [x] 6.1 运行 `python3 -m pytest tests/test_fixture_project_governance.py -q` 全绿；运行受影响既有套件 `tests/test_dashboard_fault_isolation.py tests/test_alert_lifecycle.py tests/test_dashboard_api.py -q` 无新增失败
- [x] 6.2 `python3 -m compileall core/dashboard/registry.py core/dashboard/routes/alert_routes.py bin/fixture_scheduling_showcase.py` 无语法错误；`python3 bin/fixture_scheduling_showcase.py --status` 可正常执行并输出告警记录数
