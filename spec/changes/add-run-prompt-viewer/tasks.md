## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/dashboard/routes/run_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/ClaudeOutputPane.tsx
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/runEvents.ts
  kind: modify
- path: tests/test_run_prompt_event.py
  kind: new
- path: core/dashboard/static/tests/runPromptSilence.test.mjs
  kind: new
```

## 1. 提示词落盘写点（runner.py）

- [x] 1.1 `_run_agent` 在 run_file 解析后、Popen 之前，用既有 `append_run_line`
  追加 `{"type": "prompt", "text": <完整提示词>, "timestamp": <UTC ISO8601>}`
  事件行；写点包 try/OSError pass（容错口径与 throttled-wait 写点一致），无
  车道白名单（所有经 `_run_agent` 的车道全覆盖）
- [x] 1.2 权威测试回归并按需更新「首事件/事件集合」类断言：跑
  `tests/test_daemon_lifecycle_races.py::TestRuntimeDanglingRunSweep::test_run_claude_poll_loop_crash_writes_error_terminal`、
  `tests/test_characterization_agent_runner.py`、
  `tests/test_harness_claude_snapshot.py`（锁 argv/env/stdin 快照）与
  提示词构建相关测试（`tests/test_agent_prompt_files.py` 等）；
  禁止弱化 run_metrics/终态行序断言
- [x] 1.3 新增 `tests/test_run_prompt_event.py` 锚定：impl 派发产物含恰一行
  type:"prompt" 且位于首个 CLI 事件之前；写入 OSError 不阻断派发（monkeypatch
  append_run_line 抛 OSError 后 run 照常 spawn 收尾）

## 2. 读取端点（data/runs.py + routes）

- [x] 2.1 `core/dashboard/data/runs.py` 新增 `get_run_prompt(project_root, run_id)`：
  复用 `_resolve_run_file`（含 archive/ 回退）；文件不存在返回
  `{"run_id", "exists": False, "prompt": None, "recorded_at": None, "error": None}`；
  头→尾单遍扫描首个 type=="prompt" 行命中即 early-exit；逐行 json.loads 容错
  （坏行跳过）；OSError 返回 `{"exists": True, "prompt": None, "error": "unreadable"}`
- [x] 2.2 路由接入：`run_routes.py` 新增 `_api_run_prompt`（响应
  `{"ok": true, "run_id", "prompt", "recorded_at", "project"}`，项目未知走
  `_api_run` 同款 `{"error": "unknown project"}` 200 字典契约）；`base.py` 注册
  （`_get_runs_watch` 后缀剥离分派或 GET 表 `^/api/runs/(.+)/prompt$` 前置注册，
  取改动面最小者；空/尾斜杠 run_id 沿用既有 400 校验）
- [x] 2.3 端点测试（并入 `tests/test_run_prompt_event.py` 或项目既有 runs API
  测试形态）：含记录 run 返回全文逐字节一致；历史 run（无 prompt 行）返回
  prompt=null；已归档 run 经 archive 回退可读；未知项目走既有契约；含坏行的
  产物跳过坏行不崩

## 3. 前端按钮与弹窗（static/src）

- [x] 3.1 新增前端测试 `runPromptSilence.test.mjs`（落
  `core/dashboard/static/tests/`，node --test 直载形态，对齐
  runStreamNoise.test.mjs）：type:"prompt" 事件零产出、不打断连续工具分组；
  同步在 `runEvents.ts` 的 `SILENT_KINDS` 新增 `'prompt'`（附一行注释说明来源）
- [x] 3.2 `services/dashboard.ts` 新增 `getRunPrompt(runId, project)`（与
  getRunTail 同款 withApiBase/ApiError 形态与 RunEvent 类型区注记风格）
- [x] 3.3 `ClaudeOutputPane.tsx` 工具条「加载更早事件」右侧新增「查看提示词」
  按钮（size="small" 常驻可点）+ Modal：等宽只读可滚动（max-height + overflow
  auto）、字符数展示、一键复制（clipboard + 成功提示）、加载 Spin、prompt 为
  null 显示「该 run 无提示词记录（早于功能上线，注入提示词未落盘）」、请求
  失败显示错误文案且可关闭重试；Modal 关闭即卸载内容（切 run 不串显）
- [x] 3.4 前端验证：`cd core/dashboard/static && npm test` 全绿；`npm run build`
  通过

## 4. 收尾验证

- [x] 4.1 后端相关测试全量回归（`python3 -m pytest tests/test_run_prompt_event.py
  tests/test_daemon_lifecycle_races.py
  tests/test_characterization_agent_runner.py tests/test_run_artifact_retention.py`
  及 admin_monitor 既有测试 `tests/test_admin_monitor_spec_amendment.py`）；
  其中 run_metrics/终态行序契约锚点为
  `TestRuntimeDanglingRunSweep::test_run_claude_poll_loop_crash_writes_error_terminal`；
  汇总前后端验证结果与权威测试断言更新清单
