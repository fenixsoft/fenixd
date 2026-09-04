# add-spec-manual-admin-invoke — 手动唤起 Administrator 通路

## ADDED Requirements

### Requirement: dashboard POST 触发文件信号
`POST /api/spec-admin-invoke?project=<name>&spec=<name>` 在收到请求时校验 spec 存在且无进行中 admin run，然后原子写入 `.fenix/admin_invoke_request.json`（内容含 spec、source=manual、timestamp），返回 `{ok: true}`；校验失败返回 409 及原因。

#### Scenario: 正常触发写入请求文件
- WHEN 对存在且无进行中 admin run 的 spec 调用该 API
- THEN `.fenix/admin_invoke_request.json` 出现且含目标 spec 与 timestamp，响应 ok=true

#### Scenario: spec 不存在返回 404
- WHEN 调用时指定不存在的 spec 名
- THEN 响应 404 且不产生任何文件

#### Scenario: 重复唤起被拒
- GIVEN `.fenix/admin_invoke_request.json` 已存在（未消费）或 daemon 正在跑同 spec 的 admin run
- WHEN 再次调用该 API
- THEN 响应 409「已有进行中的 Admin 处置」，请求文件保持不变

### Requirement: daemon 主循环拾取并立即唤起
daemon 主循环（1 秒粒度）检测 `.fenix/admin_invoke_request.json`：存在则读取并删除文件，随后通过 agent_runner.run_administrator 唤起 Administrator，signal_type 为 `manual-intervention`、spec 为请求中目标，指令为固定检查模板（检查该 SPEC 当前状态、定位卡住/异常原因并尝试自主治愈）；处置结果照常经 admin_store 落盘展示。

#### Scenario: 拾取后固定延迟内唤起
- GIVEN 一个已写入的 invoke 请求文件
- WHEN daemon 主循环下一轮扫描（≤2 秒）
- THEN 文件被消费删除，runs 目录出现 `admin-<spec>-<ts>.jsonl` 新 run

#### Scenario: 固定检查指令注入 prompt
- WHEN 管理员因 manual-intervention 信号被唤起
- THEN 其 prompt 含固有检查任务描述（读取 STATE.md 与相关日志、诊断 SPEC 问题）且 spec 字段指向目标

#### Scenario: 固定指令与自动检测共存不冲突
- WHEN 自动 stuck 检测与手动唤起先后发生
- THEN 二者各自独立走 store 记录与节流锚点，互不吞并对方的告警记录
