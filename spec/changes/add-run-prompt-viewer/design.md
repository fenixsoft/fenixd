# Design: add-run-prompt-viewer

## Context

运行记录窗口 = `core/dashboard/static/src/components/claude-msg/ClaudeOutputPane.tsx`
（单组件被 8 处复用）。提示词构建于 `PromptBuilder._build_prompt`
（core/agent_runner/prompt_builder.py，agents/\*.md 模板 + 动态段），以
`_run_agent(prompt, ...)` 形参进入 runner，经独立线程写入 CLI stdin
（runner.py `spawn_spec.stdin_payload`），**当前全程不落盘**。

run 产物 `.fenix/runs/<run_id>.jsonl` 是 CLI stream-json 事件 + daemon 自有
事件的混合流。daemon 自有事件先例：`provider_marker`（spawn 前写）、
`throttled-wait`（排队保活）、`run_metrics`（收尾）、`cancelled`/`error`
（终态）。**本设计把提示词作为又一自有事件行写入同一产物**，而非旁路文件。

## Goals / Non-Goals

- Goals：任何 run 的注入提示词可事后在 Dashboard 查看全文；零额外生命周期
  管理（随 run 产物归档）；对既有流消费者零破坏。
- Non-Goals：system 侧上下文（agents/\*.md 静态模板，仓内可直接读）；提示词
  编辑/重放；diff 视图。

## Decisions

### D1. 落盘形态：jsonl 自有事件行（而非旁路 .md 文件）

`{"type": "prompt", "text": ..., "timestamp": ...}` 追加进 `<run_id>.jsonl`。

- **为什么不是 `<run_id>.prompt.md` 旁路文件**：run 归档（发即归档）按
  `.jsonl` 迁移，旁路文件会成孤儿；tail/分页/读取基础设施全部长在 jsonl 上。
- **为什么不会破坏消费者**：既有消费者全部按 `type` 字段分发（前端
  `SILENT_KINDS`/分类名单、`_read_run_lines` 终态判定、`parse_run_task_done`、
  stuck 检测读文件尺寸/尾窗口）。`provider_marker` 已是「daemon 往 CLI 事件流
  写自有行」的成熟先例。total_events 计数 +1（「共 M 条事件」含 prompt 行）
  属可接受展示噪声，不做剔除特判。
- **行序契约**：权威测试 `test_run_claude_poll_loop_crash_writes_error_terminal`
  锁定的是 run_metrics/终态行次序，prompt 行写在 spawn 前（流头部、任何 CLI
  事件之前），不触碰被锁区间；实现后必须跑该权威测试 + prompt_builder 快照
  测试确认。

### D2. 写点：`_run_agent` 内 run_file 解析后、Popen 前（runner.py）

- 单一咽喉：所有车道（dispatch 家族、maintenance、admin、dispute-judge、
  spec-review、交互式）全部经 `_run_agent`，无白名单。
- 用既有 `append_run_line`（run_files.py，带并发交错防护）+ try/OSError pass，
  容错口径与 throttled-wait 写点一致。
- `timestamp` 用 `datetime.now(timezone.utc).isoformat()`（与既有自有事件行
  同款；仓库全链 UTC 纪律）。

### D3. 读取端点：`GET /api/runs/<run_id>/prompt?project=<name>`

- 数据层：`core/dashboard/data/runs.py` 新增 `get_run_prompt(project_root, run_id)`，
  复用 `_resolve_run_file`（活跃 + archive/ 两处回退，与 `get_run_events` 同源）。
  文件头→尾单遍扫描，`type=="prompt"` 命中即 early-exit；逐行
  `json.loads` 容错（坏行跳过）；OSError → `{"exists": True, "prompt": null,
  "error": "unreadable"}` 口径对齐 `get_run_events`。
- 路由：两种等价实现任选其一——(a) `_get_runs_watch`（routes/base.py:330）
  的后缀剥离式（`rest.endswith("/prompt")` 分派 `s._api_run_prompt(run_id, q)`，
  与 `/watch` 同款）；(b) GET 表新增 `^/api/runs/(.+)/prompt$` 且注册在
  `^/api/runs/(.+)$` 之前。实现者按改动面最小者取。
- 响应形状：`{"ok": true, "run_id": ..., "prompt": <str|null>,
  "recorded_at": <str|null>, "project": <name>}`；run 文件不存在 →
  `prompt: null`（不 404，弹窗按无记录提示——与 `_api_run` 的
  200+exists 字典契约同哲学）。项目未知 → 沿用 `_api_run` 的
  `{"error": "unknown project"}` 200 字典契约。
- 热路径属性：按钮点击才调用（非轮询），扫描最坏 O(文件) 但单次点击可接受，
  不做缓存。

### D4. 前端：按钮 + Modal（ClaudeOutputPane.tsx 单点）

- 按钮位置：工具条「加载更早事件」Button 右侧，`size="small"` 同款；
  常驻可点。
- Modal：antd Modal（宽 ~880px），内容为等宽（`font-family: monospace` 系
  token）只读 `<pre>`，`max-height` + `overflow: auto`；头部/脚注显示字符数；
  「复制」按钮（`navigator.clipboard.writeText`，成功 message 提示）；加载中
  Spin；`prompt: null` → 「该 run 无提示词记录（早于功能上线，注入提示词未落盘）」；
  请求失败 → 错误文案 + 可关闭重试。
- service：`services/dashboard.ts` 新增 `getRunPrompt(runId, project)`，与
  `getRunTail` 同款 `withApiBase` + ApiError 形态。
- 静默：`runEvents.ts` 的 `SILENT_KINDS` 集合新增 `'prompt'`（一处 + 注释）。
  注意 runEvents.ts 注释约定「本模块不得新增运行时相对导入」，本改动不涉
  导入。

## Risks / Trade-offs

- **[产物体积]** 大提示词（数十 KB）单行写入产物 → 磁盘占用小幅上升；tail
  尾读窗口（64KB）与流式扫描不受影响（prompt 行在流头部）。接受。
- **[行序测试]** 既有权威测试若断言「首个事件」形态（如 init 前无行）可能
  需要更新断言 —— 实现时跑
  `tests/test_run_claude_poll_loop_crash_writes_error_terminal`、
  `tests/test_characterization_agent_runner.py`、prompt_builder 快照测试，
  仅允许更新「事件集合/首行」类断言，MUST NOT 弱化 run_metrics/终态行序断言。
- **[admin_monitor 文本规则]** 自有事件行进入转录后，文本规则扫描按行 JSON
  解析分发，prompt 正文理论上可能命中规则关键词 —— 现状 `provider_marker`/
  `run_metrics` 同样携带 daemon 文本已共存；实现时以
  admin_monitor 既有测试回归确认零误报，不做预防性改动。
- **[敏感信息]** 提示词为任务指令文本，不含凭据（凭据走 env_overrides）；
  Dashboard 既有无鉴权面（内网反代）一致暴露，无新增面。

## Migration Plan

无状态迁移。上线后新 run 开始落盘 prompt 行；历史 run 按「无记录」提示，
无需回填（数据当时不存在）。

## Open Questions

无（执行模式 fast-track、立即执行已由用户确认）。
