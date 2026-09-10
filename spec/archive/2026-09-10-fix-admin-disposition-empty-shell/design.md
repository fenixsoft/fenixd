# Design: fix-admin-disposition-empty-shell

## Context

Administrator 处置链路：AdminMonitor 检测困境信号 → `_invoke_administrator`（`core/admin_monitor.py:784`）→ `run_administrator`（`core/agent_runner/runner.py:351`）唤起 Administrator CLI，agent 按 prompt 把处置结果写入实例文件 `.fenix/admin_disposition-<run_id>.json` → run 结束后 daemon 读该文件构造 `AdminDisposition` → `_invoke_administrator` 落 final disposition 到 `admin_alerts.json`。

两条真实事故（2026-09-02 `admin-add-spec-archive-1788348989`、2026-09-03 `admin-fix-implementer-task-progress-1788417611`）证实：CLI 异常死亡时实例文件从未写出，`disp` 读取为空 dict，`AdminDisposition` 各文本字段落到 `or ""` 兜底，`result` 兜底 `"failed"`；`_invoke_administrator` 原样落盘形成空壳。失败原因（`AdminDisposition.error`，runner.py:449 已赋值）止步于内存——落盘字段清单（admin_monitor.py:826-838）不含 error，异常路径也不打日志（对照：dispatch 通用路径在 runner.py:1053 有 `ended in error` DEBUG 日志）。

UI 侧 `activities/index.tsx:94-104`：`summary` 为空时渲染兜底文案"（无叙述总结）处置：— · 结果：failed"；`error` 字段因数据端不存在而无从展示。

## Goals / Non-Goals

**Goals**

- 失败的 final disposition 记录自解释：error + signal 兜底字段
- 失败路径产生可检索的 WARNING 日志
- v3 activities 页展示失败原因
- 向后兼容：存量记录（无 error 键）与成功记录行为不变

**Non-Goals**

- 不追查 09-03 SIGTERM 的发送者（独立问题，本 spec 只保证下次能看见）
- 不改 pending 占位记录结构、不迁移存量 admin_alerts.json 数据
- 不改 `AdminDisposition` 数据类结构（error/output 字段已存在）
- 不处理 run 转录 jsonl 的保留策略（"查看处置过程"按钮对已清理转录的白搭问题另行立项）

## Decisions

### D1: 兜底逻辑放在 admin_monitor 落盘处，不改造 runner 的 AdminDisposition 构造

落盘前的最后一步是 `_invoke_administrator`（admin_monitor.py:826-838），在此处对 `disp.result == "failed"` 的记录做字段兜底（error 注入、recommended_action 回退到 signal），改动集中、语义清晰。runner 侧仅补一条 WARNING 日志（error 变量已有），不动 `AdminDisposition` 构造——避免影响 `_apply_family_waiver`、escalation 分支等所有 disp 消费方。

### D2: error 兜底值为 `disp.error or ""`，写入新可选键 `error`

`admin_alerts.json` 是 append 型 jsonl 风格存储，读侧（dashboard data 层）按字段访问、缺键安全。新增可选键不迁移存量数据：旧空壳记录无 error 键时 UI 按现状渲染（保持向后兼容 scenario），新记录一律带键（成功时为空字符串）。

### D3: UI 展示位置——result pill 附近的醒目行 + 空 summary 兜底文案区合并展示

activities 页 `ActivityCard`：当 `a.error` 非空时，在 body 区域顶部渲染红色系失败原因行（`Typography.Text type="danger"` 级别样式，前缀"失败原因："）；同时把现有空 summary 兜底文案改为附带 error。两处共用同一数据，避免"error 在 pill 里被截断"的可读性问题。antd v6 渲染，遵循 v3 现有 PRE_WRAP 样式惯例。

### D4: 日志级别 WARNING、component 沿用 `agent_runner`

与 dispatch 路径 `fast-track failed ...`（WARNING）同级同类；message 格式 `Administrator run <run_id> failed: <error>`，保证 `grep "Administrator run"` 可一次检索全部失败。

## Risks / Trade-offs

- `disp.result == "failed"` 判定覆盖 escalate 路径吗？——escalation 分支（admin_monitor.py:850-867）独立落 ESCALATION 记录，disposition 兜底仅作用于 DISPOSITION 记录本身，互不干扰；escalate=True 且 result=failed 时两条记录都带全上下文。
- 重启生效窗口：改 `core/*.py` 后需 touch `.fenix/restart_request` 优雅重启 daemon，否则进程跑旧码（已知坑，tasks 中显式列步）。
- dist 产物：UI 改动需重建 dist 并随分支提交，否则主树 :8787 验证全量假阴性（已知坑，tasks 中显式列步）。

## Migration Plan

无数据迁移。新增键 `error` 为可选，读侧缺键安全；daemon 重启后新记录生效。

## Open Questions

无。
