<!-- knowledge: capability=v2-run-stream-modal rev=1 sources=spec/archive/2026-09-06-v2-run-stream-modal -->

# v2 运行记录弹窗

run 流实时渲染组件：run 模式订阅运行事件流，admin 模式经等待态状态机接入。

## 现行规则

- run 模式（`mode=run, runId`）：打开即 `GET /api/runs/<runId>?tail=300` 渲染尾部，随后 `POST /api/runs/<runId>/watch?cid=<Bridge.cid>` 订阅；SSE `run_events` 帧（run_id 匹配）增量追加，reset 帧整段替换。
- 事件按 behavior.md §3 形态渲染（含 thinking_tokens 合并、marked 转义）；粘性滚动以 40px 为阈值：上翻释放自动滚动、回底恢复；展示 token 统计。
- 关闭清理：Dialog close 时 `DELETE /api/runs/<runId>/watch?cid=` 并关闭本组件的 EventSource。
- admin 模式（`mode=admin, project, spec`）：先 `POST /api/spec-admin-invoke`——409 时错误 toast（6 秒窗口）并终止、不发 watch；成功进入等待态，每 5s `GET /api/specs/<spec>` 解析 `admin_run_id`，拿到后按 run 模式拉流；关闭时同样清理。
- 弹窗隐藏与轮询失败均有显式恢复路径。

## 溯源

- 史前复原 — v2 运行记录弹窗 watch 增量渲染 + 粘性滚动 + token 统计；弹窗隐藏与轮询失败有显式恢复
- 2026-09-06 v2-run-stream-modal — 落地 run/admin 双模式订阅契约（tail 预取 + watch 订阅 + reset 整段替换）、关闭退订清理与 admin 等待态状态机（409 终止 / admin_run_id 轮询切换）
