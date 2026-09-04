# add-run-cancel — Tasks

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/RunCancelModal.tsx
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: modify
- path: tests/test_run_cancel.py
  kind: new
```

## 1. runner 核心取消原语

- [x] 1.1 `runner.py`：新增 `RunCancelledError` 异常类（携带 reason）；AgentRunner 增加锁保护的 `_cancel_requested: set[str]` 旗标集合与基础 run_id 归一化助手（正则剥 `-a<n>` attempt 后缀）
- [x] 1.2 `runner.py`：实现 `cancel_run(run_id, reason="", by="admin") -> dict`——归一化→前缀匹配 `_running_agents` 活跃 attempt→命中则登记旗标返回 `{"status": "cancel_requested", "attempts": [...]}` 并落 minor 级 `run_cancelled` 审计记录，未命中返回 `{"status": "not_running"}`；docstring 固化契约：仅供外部管理动作调用，状态机及自动链路（transition/recovery/gate/freeze）不得调用，方法自身不做任何状态转换、不写 status 字段
- [x] 1.3 `runner.py`：`_run_claude` 轮询环（1s 粒度）加旗标检查——命中则 `terminate()` → 最长 `AGENT_TERMINATE_GRACE_SECONDS`（10s）等待 → 存活则 `kill()`；读线程 join 后向 run jsonl 追加 `{"type": "cancelled", "reason", "by", "timestamp"}` 终态行（保证末行），抛 `RunCancelledError`
- [x] 1.4 `runner.py`：`AgentRunResult` 增加 `cancelled: bool = False` 字段并随 `to_dict` 序列化
- [x] 1.5 `runner.py`：`_execute_agent` attempt 循环顶部（与 frozen 检查同位置）加旗标检查，命中立即返回不派发 attempt、不创建 worktree；通用 `Exception` 之前单独捕获 `RunCancelledError`——不重试、不调用 `_record_instant_fail`、不触发 provider 切换，返回 `cancelled=True` 失败结果（error 含 "cancelled by admin" 与 reason）；run 收尾清理旗标

## 2. dispatch hold-state 处置

- [x] 2.1 `dispatch.py`：`_run_agent_worker` implementer/fast-track 分支对 `cancelled=True` 结果走 hold-state——只更新 error 字段（含 "run 被人工取消" 与 reason），不翻转 status、不动 `_retry_count`/`_merge_fp`/`_merge_streak`、不入队重派
- [x] 2.2 `dispatch.py`：verifier 验证流水线与 repair worker 对取消结果同语义 hold-state（verifier 取消后 spec 保持 testing 原状）

## 3. 文件信号与 daemon 消费

- [x] 3.1 `data.py`：`request_run_cancel(project_root, run_id, reason)`——tmp+rename 原子写 `.fenix/cancel_run_request.json`（run_id/reason/source/created）；存在未消费请求时返回含既有 created 时间戳的冲突结构，不覆盖
- [x] 3.2 `fenixd.py`：主循环新增 `_check_cancel_requests()`——镜像 `_check_admin_invoke_requests`（读→删→校验 run_id 非空→调 `agent_runner.cancel_run(run_id, reason, by=source)`；损坏 JSON 删除防卡死；删除失败本轮跳过下轮再试）；不投 worker 池

## 4. API 与 UI

- [x] 4.1 `server.py`：`POST /api/run-cancel?project=&run_id=`（可选 reason）——项目不存在 404、run_id 缺失 400、待消费请求冲突 409、受理 200 `{"requested": true}`
- [x] 4.2 `services/dashboard.ts`：run-cancel 客户端函数；`detail.tsx` runs 列表活跃 run 行加「终止」操作；新建 `RunCancelModal.tsx` 确认弹窗（展示 run_id + 可选 reason 输入），确认才发起请求，受理后行内反馈
- [x] 4.3 前端构建：dist 产物重建并提交（`core/dashboard/static/dist/`，锚点 `index.html`）

## 5. 测试与回归

- [x] 5.1 `tests/test_run_cancel.py` runner 单测：活跃 run 取消返回 cancel_requested 且子进程被终止、jsonl 末行为 cancelled 终态行；attempt 1 被取消无 `-a2` 文件；attempt 间隙设旗标不派发下一 attempt；已结束 run 返回 not_running；`-a2` 与基础 run_id 两种调用等价命中；取消不增秒挂计数；`to_dict` 含 `cancelled: true`；cancel_run 全程不触碰 spec status 字段
- [x] 5.2 dispatch 单测：implementing spec 实现运行被取消后 status 保持 `implementing`、`_retry_count` 不变、error 含 "run 被人工取消"、无入队；testing spec verifier run 被取消后 status 保持 `testing`
- [x] 5.3 信号链路测试：合法请求文件被消费（cancel_run 被调、文件删除）；损坏 JSON 文件被删不抛异常；重复请求返回冲突；API 400/404/409/200 语义
- [x] 5.4 全量回归：`pytest tests/` 通过；dashboard 冻结/唤醒等既有 admin 入口行为不受影响
