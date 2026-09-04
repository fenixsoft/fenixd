# Design: add-spec-context-menu

## Context

Dashboard 的 spec 列表（`core/dashboard/static/app.js` specRow）当前仅渲染「文档」链接与 error 信息子行「清除」按钮（先例：`clearSpecError` → `POST /api/spec-error-clear` → 原子写 STATE.md）。Administrator 现只能由 daemon 内 admin_monitor 线程按 30 分钟周期自动唤起，无手动入口。spec 删除无任何界面/接口支持；优先级只能手改 STATE.md。

server.py（独立进程）与 fenixd daemon 通过文件共享通信已有成熟先例：`.fenix/restart_request`（supervisor 轮询）、admin_alerts.json（flock）。手动唤起 admin 沿用文件信号模式最贴合现状。

## Goals / Non-Goals

- Goals: 三项运维动作全部收敛进右键菜单；手动唤起 ≤2 秒内生效；软删除可恢复、幂等
- Non-Goals: 不做权限体系（本机单用户）；不做批量操作；不做归档的 UI 恢复功能（手工 mv 即可恢复）；不改变 admin_monitor 自动检测

## Decisions

### D1 右键菜单为自绘 DOM 组件
全局 `contextmenu` 监听 + `preventDefault()`（仅当 target 在 spec 行内）。菜单元素固定复用（隐藏/显示切换），位置计算含视口翻转。Esc/click-outside/scroll 关闭。样式沿用现有 CSS 变量（--surface、--hairline），保证明暗主题一致。

### D2 手动唤起走文件信号而非直接进程调用
dashboard server 进程与 daemon 分离，禁止 server 直接起 agent（会绕过 state_machine 与 token 预算）。链路：
1. server handler 校验（spec 存在、请求文件不存在）→ 原子写 `.fenix/admin_invoke_request.json`
2. daemon 主循环（现有 `while self.running: time.sleep(1)` 处）新增检测分支：读→删文件→构造 signal dict（signal_type=manual-intervention）→ 调 agent_runner.run_administrator(signal)
3. 「进行中拒绝」判定：请求文件存在即拒（server 侧）；daemon 侧拾取前同 spec 已有 running admin 也拒（记录 disposition 说明）

选择文件信号：与 restart_request 同构、零新增依赖、崩溃安全（残留文件重启后仍会被消费）。

### D3 固定检查指令模板复用 administrator prompt
run_administrator 已接受 detail signal 构造 prompt。manual-intervention 信号的 description 固定为「人工呼叫：检查 SPEC <name> 出现什么问题并尝试处置」。不新增 prompt 分支，现有 administrator prompt 完全适用（其铁律已覆盖先诊断后动手、留痕、可升级）。

### D4 删除 = remove_spec + 目录移动到 archive
state_machine 新增 `remove_spec(name)`（read_all → pop → write_all，原子写与现有锁语义一致）。目录用 `shutil.move` 到 `spec/archive/<name>-<Unix秒>/`。archive 根目录与项目扫描的隔离：event_bus/pm_engine 只扫 spec/changes/<name> 直接子目录且过滤 archive 目录名，实现时需确认扫描逻辑对 archive 前缀天然免疫（若否则加显式排除）。
运行中保护：检查 runs 目录该 spec 是否有 mtime 在最近 120 秒内更新的 run 文件，有则 409。

### D5 优先级弹窗复用系统 `prompt()`
P1-P9 输入框无需自定义组件，浏览器 prompt 预填当前值，取消返回 null 即中止。服务端仍强校验（防绕过）。

## Risks / Trade-offs

- 手动唤起被频繁点击 → 每次一个完整 LLM run 有成本；靠 409（请求文件存在）+ 进行中提示缓解，暂不加频次限制（本机工具）
- 软删除后 spec 目录带时间戳后缀，恢复时需手工去掉后缀移回——已接受的恢复方式
- 与并行 git 操作冲突风险低：STATE.md 被 .gitignore 忽略，spec 归档移动产生的删除由用户后续正常提交

## Open Questions

- 无
