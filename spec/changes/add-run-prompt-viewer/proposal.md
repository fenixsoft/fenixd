# Proposal: add-run-prompt-viewer

## Why

运行记录窗口（ClaudeOutputPane）目前只能看到 agent 运行期间产出的事件流（assistant /
工具调用 / 工具结果 / result），**看不到该次运行被注入的任务提示词**。提示词由
`PromptBuilder._build_prompt` 动态构建（agents/\*.md 模板 + 动态段填充），经
`_run_agent` 通过 stdin 喂给 CLI，**全程不落盘**——事后排查「agent 为什么这么做」
「这一棒的输入到底是什么」时只能靠人工拼装模板反推，取证成本高。

## What Changes

1. **提示词落盘**（core/agent_runner/runner.py）：`_run_agent` 在 spawn 子进程前，
   向 run 产物 `<run_id>.jsonl` 追加一行 daemon 自有事件
   `{"type": "prompt", "text": <完整提示词>, "timestamp": ...}`（与既有
   `provider_marker` / `run_metrics` / `throttled-wait` 自有事件同实践）。
   提示词随 run 产物走既有归档生命周期，零额外生命周期管理。
2. **读取端点**（core/dashboard/data/runs.py + routes）：新增数据层
   `get_run_prompt(project_root, run_id)`（复用 `_resolve_run_file`，含 archive
   回退）+ 路由 `GET /api/runs/<run_id>/prompt?project=<name>`。
3. **前端查看按钮**（ClaudeOutputPane.tsx）：工具条「加载更早事件」旁新增
   「查看提示词」按钮，点击弹 Modal 展示提示词全文（等宽字体、可滚动、带复制
   按钮与字符数）。无记录（功能上线前的历史 run）时展示明确提示。
4. **流渲染静默**（runEvents.ts）：`prompt` 事件加入 `SILENT_KINDS`，不作为
   噪声行出现在消息流中。

## Capabilities

### 新能力

- **run-prompt-viewer**：run 注入提示词的落盘、读取与查看。

### 受影响既有能力

- 无活跃既有能力受影响。归档能力 `add-run-record-readability`（2026-09-27 归档，
  spec/archive/2026-09-27-add-run-record-readability；其 1.5 交付引入
  runEvents.ts 的 SILENT_KINDS 静默名单）将新增 `prompt` 一项，该扩展由本
  change 的 run-prompt-viewer 能力自带 Requirement 承载。

## Impact

- **代码**：`core/agent_runner/runner.py`（一处写点）、
  `core/dashboard/data/runs.py`（数据层只读函数）、
  `core/dashboard/routes/run_routes.py` + `routes/base.py`（端点与路由注册）、
  `core/dashboard/static/src/services/dashboard.ts`（service 函数）、
  `core/dashboard/static/src/components/claude-msg/ClaudeOutputPane.tsx`
  （按钮 + Modal）、`.../claude-msg/runEvents.ts`（静默名单）。
- **兼容性**：历史 run 无 prompt 行 → 端点返回 `prompt: null`，前端显示
  「无记录」；事件行序契约测试（`test_run_claude_poll_loop_crash_writes_error_terminal`
  等）锁定的是 CLI 事件行序，prompt 行写在 CLI 事件之前、自有事件之间次序
  需跑权威测试确认不破坏既有断言。
- **非目标**：不展示 system 侧上下文（agents/\*.md 等静态模板文件可直接读仓内
  真相源）；不做提示词 diff/历史对比；不做权限控制（Dashboard 既有面一致）。
