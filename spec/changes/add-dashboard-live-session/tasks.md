## Deliverables

```yaml
- path: core/dashboard/session_manager.py
  kind: new
- path: core/dashboard/routes/session_routes.py
  kind: new
- path: core/dashboard/static/src/pages/projects/components/SessionModal.tsx
  kind: new
- path: tests/test_dashboard_session.py
  kind: new
- path: core/dashboard/static/tests/sessionEvents.test.mjs
  kind: new
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/routes/__init__.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/runEvents.ts
  kind: modify
- path: core/dashboard/static/package.json
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 说明：`core/dashboard/static/dist/`（前端构建产物）不入库，由框架在 merge 后
> 自动重建，属 `reference` 非交付物。

## 1. 会话进程管理器（D1 / D2 / D5）

- [ ] 1.1 新建 `core/dashboard/session_manager.py`：定义模块常量
  `SESSION_EVENT_BUFFER = 4000`、`SESSION_IDLE_TIMEOUT_SECONDS = 1800`、
  `SESSION_TERMINATE_GRACE_SECONDS = 5`，与 `Session` 数据类
  （`project / project_path / proc / session_id / events / lock / last_activity /
  stderr_tail`）及 `SessionManager` 类骨架。
- [ ] 1.2 实现 `SessionManager.start(project_name, project_path) -> Session`：
  若既有会话存活则复用；否则以 D1 的命令行与 `cwd=project_path`、
  `env=os.environ.copy()` 启动 `subprocess.Popen(stdin=PIPE, stdout=PIPE,
  stderr=PIPE, text=True, bufsize=1)`，`session_id` 用 `uuid4().hex` 生成。
  MUST NOT 从 `.fenix/config.yaml` 读 provider 配置。
- [ ] 1.3 实现每会话的 **stdout 读线程**：逐行读取，`json.loads` 成功且**非
  hook 噪音**（见 1.9）的以 `{"type": …, **原始字段, "ts": time.time()}` 形态
  append 到 `events` 并
  `hub.broadcast({"type":"session_events","session_id":sid,"events":[ev]}, run_id=sid)`；
  解析失败以 `{"type":"stderr","line":…}` 兜底。读到 EOF 时追加
  `{"type":"session_ended","session_id":sid,"reason":"process_exit"}`、广播、
  并从 manager 登记移除该会话。
- [ ] 1.4 实现每会话的 **stderr 读线程**：逐行读入 `stderr_tail`（有界 deque，
  上限 200 行），不广播、不进 `events`。
- [ ] 1.5 实现 `SessionManager.send(sid, text) -> None`：非空校验后，在
  `session.lock` 保护下向 stdin 写入 D1 规定的单行 JSON（`ensure_ascii=False`）
  并 `flush()`；刷新 `last_activity`。会话不存在 / 进程已退出时抛可被路由层
  转为 4xx 的异常。
- [ ] 1.6 实现 `SessionManager.stop(sid, reason) -> None` 与内部 `_terminate(session,
  reason)`：关 stdin → 等 `SESSION_TERMINATE_GRACE_SECONDS` → 仍存活则 `kill()`；
  追加并广播对应 `reason` 的 `session_ended` 事件；从登记移除。幂等
  （对已移除会话调用为 no-op）。
- [ ] 1.7 实现空闲回收：manager 启动一条守护线程，按
  `SESSION_IDLE_TIMEOUT_SECONDS` 周期扫描，`now - last_activity` 超限的会话走
  `_terminate(session, "idle")`。线程 MUST 不因单次扫描异常而退出
  （异常记日志后继续）。
- [ ] 1.8 实现 `SessionManager.shutdown()`：终止全部会话（遍历 + `_terminate`），
  停止空闲回收线程；MUST 幂等。
- [ ] 1.9 实现 hook 噪音过滤（design D1.1）：读线程在**进缓冲与广播之前**丢弃
  `type == "system"` 且 `subtype` 以 `hook_` 开头的事件；其余事件（含
  `system/init`）一律保留。过滤 MUST 只作用于会话路径，MUST NOT 触及
  `agent_runner` 的落盘逻辑。

## 2. REST 端点与路由登记（D3）

- [ ] 2.1 新建 `core/dashboard/routes/session_routes.py`，实现
  `H_SessionRoutesMixin`：
  - `_api_session_get(query)` → `GET /api/session?project=<name>`：校验项目存在
    且路径存在（否则 4xx）；无会话时返回 `{"session": null, "events": []}`；
    有会话时返回 `{"session": {"id": sid, "started_at": …},
    "events": [...], "truncated": <bool>}`。
  - `_api_session_send(query)` → `POST /api/session/send?project=<name>`：读 JSON
    body `{"text": "..."}`；空/空白 → 400；项目或会话缺失 → 404；成功 →
    `{"ok": true}`。
  - `_api_session_stop(query)` → `POST /api/session/stop?project=<name>`：
    终止会话，返回 `{"ok": true}`（无会话时亦 200 幂等）。
  - `_api_session_watch(run_id, query, watch)` → `POST`/`DELETE`
    `/api/session/watch?project=<name>&cid=<cid>`：`hub.watch/unwatch(cid, sid)`。
- [ ] 2.2 在 `core/dashboard/routes/base.py` 的 `_API_GET_ROUTES`（1 条
  `/api/session`）、`_API_POST_ROUTES`（3 条：`/api/session/send`、
  `/api/session/stop`、`/api/session/watch`）、`_API_DELETE_ROUTES`（1 条
  `/api/session/watch`）中按既有条目结构 `(kind, pattern, handler, json_flag)`
  登记新路由。**顺序陷阱（强制）**：POST 链末有 4 个裸 `endswith`
  （`/start` `/stop` `/restart` `/install-hosting`，`base.py:294-297`），其中
  `/stop` **会误匹配 `/api/session/stop`** —— 故新路由 MUST 作为**精确条目**放在
  裸 `endswith` 组**之前**（与 `/api/project/describe` 同处精确区），MUST NOT
  落在后缀组之后。
- [ ] 2.3 在 `core/dashboard/routes/__init__.py` 门面 re-export 新 mixin，并在
  `core/dashboard/server.py` 的 `DashboardHandler` 继承列表中加入新 mixin
  （MRO 中须排在 `BaseHTTPRequestHandler` 之前）。
- [ ] 2.4 路由图一致性：运行 `python3 bin/gen-route-map.py` 并确认新端点出现在
  生成的路由图中（若该脚本有 `--check` 模式则以其为准）。

## 3. 服务器生命周期接线（D2 / D5）

- [ ] 3.1 `core/dashboard/server.py`：`DashboardHTTPServer.__init__` 中新增
  `self.session_manager = None` 占位（与 `self.watcher = None` 同级）。
- [ ] 3.2 `serve()`：在 `watcher.start()` 之后创建
  `SessionManager(httpd.sse_hub)` 并赋给 `httpd.session_manager`；启动空闲回收线程。
- [ ] 3.3 `serve()` 的 `finally` 中，在 `watcher.stop()` **之前**调用
  `httpd.session_manager.shutdown()`，确保 dashboard 退出不留会话子进程。

## 4. 前端会话界面（D6 / D7）

- [ ] 4.1 `static/src/services/dashboard.ts`：新增 `getSession(project)`、
  `sendSessionMessage(project, text)`、`stopSession(project)`、
  `registerSessionWatch(project, cid)`、`unregisterSessionWatch(project, cid)`
  五个客户端函数（沿用既有 `request<T>()` 封装）。
- [ ] 4.2 新建 `static/src/pages/projects/components/SessionModal.tsx`：
  - props：`{ project: string; open: boolean; onClose(): void }`。
  - 打开（`open` 由 false→true）时：`getSession(project)` 拉全量 →
    建立 `EventSource('/api/stream')` → 在 `hello` 分支用服务端 cid
    `registerSessionWatch` → 再 `getSession` 重拉一次（兜住注册前的窗口）。
  - `session_events` 消息按 `session_id === 当前会话 id` 过滤后 append；
    按事件 `uuid` 去重（无 `uuid` 的事件不去重）。
  - `session_ended` 消息 → 置终态、禁用输入区、显示结束提示。
  - 消息区渲染 `ClaudeMessageList messages={runEventsToChatMessages(events)}`；
    输入区 `Input.TextArea` + 发送按钮 + 「停止会话」按钮；发送中禁用输入。
  - 卸载 / `onClose` 时：`unregisterSessionWatch`、`eventSource.close()`。
- [ ] 4.3 `static/src/pages/projects/list.tsx`：在 `PageContainer.header.title`
  内把现有 `<Space>` 改为一行 flex 容器，右端（`marginLeft:'auto'`）加
  「接入会话」`Button`（`icon={<MessageOutlined />}` 或等价），点击
  `setSessionOpen(true)`；页面底部渲染 `<SessionModal project={name} …/>`。
  MUST 保持 `共 N 个 SPEC` 文案位置不变，且移动端布局不溢出。
- [ ] 4.4 `static/src/components/claude-msg/runEvents.ts`：为会话终态事件
  `{"type":"session_ended", "reason": …}` 增加明确分支，渲染为中文系统行
  （区分 `reason` 为 `idle` / `process_exit` / `user`）；MUST NOT 落到
  fallback 的 `[session_ended]` 形态。（对应 design「Open Questions」第 1 条，
  已定：在 `runEvents.ts` 收口。）

## 5. 测试（含真实进程集成测试）

- [ ] 5.1 `tests/test_dashboard_session.py`：单元测试 `SessionManager` ——
  复用语义（同项目二次 `start` 返回同一句柄）、空文本拒绝、对不存在会话 `send`
  抛错、`stop` 幂等、`shutdown` 终止全部。
- [ ] 5.2 同文件：以 `monkeypatch` 把 `subprocess.Popen` 换为可注入的假进程，
  验证 stdout 读线程把 JSON 行转事件、脏行转 `stderr` 事件、EOF 转
  `session_ended(process_exit)`，并验证 `hub.broadcast` 收到对应消息。
- [ ] 5.3 同文件：路由层测试 —— `GET /api/session` 在无会话 / 有会话两种情形
  的响应形态（含 `truncated` 标记），`POST /api/session/send` 的 400/404/200
  分支，`POST/DELETE /api/session/watch` 调用到 `hub.watch/unwatch`。
- [ ] 5.4 **真实进程集成测试**（标记为可跳过：环境无 `claude` CLI 时 `skip`）：
  实际启动一个会话进程，连续发送两轮文本，断言两轮均在事件流中产生 assistant
  事件（验证 `--input-format stream-json` 的长期存活语义未随 CLI 版本改变）。
  测试 MUST 在 finally 中终止该进程。
- [ ] 5.5 前端测试：新增 `core/dashboard/static/tests/sessionEvents.test.mjs`
  （与既有 `tokens.test.mjs` 同形态，`node --test` 零依赖跑 `.ts` 源），
  为 `runEventsToChatMessages` 的 `session_ended` 分支补用例：断言
  `{"type":"session_ended","reason":"idle"}` 等三种 reason 各自渲染为明确的
  中文系统行（**非** fallback 的 `[session_ended]`），且既有 run 事件分支
  不回归。该测试文件须加入 `core/dashboard/static/package.json` 的测试脚本
  或 CI 入口（与 `tokens.test.mjs` 同处）。
