<!-- knowledge: capability=add-spec-manual-admin-invoke rev=1 sources=spec/archive/2026-09-03-add-spec-context-menu -->

# SPEC 菜单手动唤起管理员

SPEC 级手动唤起 Administrator 的端到端通路：dashboard API → 文件信号 → daemon 拾取 → manual-intervention 处置 run。

## 现行规则

- 手动唤起入口为 `POST /api/spec-admin-invoke?project=<name>&spec=<name>`：校验 spec 存在且无进行中 admin run 后，原子写入 `.fenix/admin_invoke_request.json`（含 spec、source=manual、timestamp），返回 ok；spec 不存在返回 404 且不产生任何文件。
- 已存在未消费的请求文件、或该 spec 的 admin run 正在执行时，重复唤起返回 409「已有进行中的 Admin 处置」，请求文件保持不变。
- daemon 主循环（1 秒粒度）检测 `.fenix/admin_invoke_request.json`：存在即读取并删除，经 `agent_runner.run_administrator` 唤起 Administrator，signal_type 为 `manual-intervention`、spec 指向请求目标；从拾取到唤起不超过 2 秒。
- manual-intervention 唤起的 prompt 携带固定检查模板：读取 STATE.md 与相关日志、诊断该 SPEC 卡住/异常原因并尝试自主治愈。
- 处置结果照常经 admin_store 落盘展示（admin_alerts.json / 处置记录）。
- 手动唤起与自动 stuck 检测共存：二者各自独立走 store 记录与节流锚点，互不吞并对方的告警记录。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：手动唤起 Admin 写文件信号（admin_invoke），daemon 主循环拾取信号后唤起 Administrator，manual-intervention 指令进入 admin prompt
- [2026-09-03 add-spec-context-menu](spec/archive/2026-09-03-add-spec-context-menu/) — 落地 SPEC 级手动唤起端到端通路：dashboard POST API、请求文件校验（404/409）、daemon 2 秒拾取与固定检查指令注入，明确与自动检测的节流隔离
