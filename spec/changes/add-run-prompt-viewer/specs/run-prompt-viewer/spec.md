## ADDED Requirements

### Requirement: 注入提示词落盘为 run 事件行

系统 SHALL 在 `_run_agent` spawn CLI 子进程之前，向该 run 的产物文件
`.fenix/runs/<run_id>.jsonl` 追加一行 daemon 自有事件：

```json
{"type": "prompt", "text": "<完整注入提示词>", "timestamp": "<UTC ISO8601>"}
```

- 写点 MUST 在 Popen 之前（保证 CLI 事件之前可读到 prompt 行）；planner 节流
  排队等路径可能先写入 `throttled-wait` 行，prompt 行 MUST 以 `type` 字段被
  消费者识别，MUST NOT 依赖「物理首行」位置。
- 写失败（OSError）MUST NOT 阻断 run 派发（与既有 `append_run_line` 容错口径
  一致）。
- 该行为 MUST 覆盖所有经 `_run_agent` 的车道（impl/planner/code-fix/
  code-review/verifier/dispute-judge/spec-review/administrator/maintenance/交互式），
  无车道白名单。

#### Scenario: impl run 落盘提示词

- **WHEN** 任一 impl run 经 `_run_agent` 派发，注入提示词为 "实现 X 功能…"
- **THEN** `.fenix/runs/<run_id>.jsonl` 中存在恰一行
  `{"type":"prompt","text":"实现 X 功能…",...}`，且其行位置在首个 CLI 事件
  （`system`/`assistant`）之前

#### Scenario: 写失败不阻断派发

- **WHEN** prompt 行写入抛 OSError（如目录只读）
- **THEN** run 照常 spawn 与执行，无异常上抛

#### Scenario: 车道全覆盖

- **WHEN** administrator 车道与 impl 车道各派发一次 run
- **THEN** 两个 run 的产物文件各含一行 `type:"prompt"` 事件，`text` 分别为
  各自车道的完整注入提示词

### Requirement: prompt 事件行流渲染静默

前端 run 事件转聊天气泡时 SHALL 将 `type:"prompt"` 事件静默丢弃（加入
`SILENT_KINDS`），不产生任何可见行、不打断连续工具分组——提示词只经
「查看提示词」按钮按需展示。

#### Scenario: prompt 行不出现在消息流

- **WHEN** run 事件流含 `{"type":"prompt","text":"..."}` 行
- **THEN** 消息列表不渲染该行，相邻工具分组不被打断

### Requirement: 查看提示词按钮与弹窗

运行记录面板（ClaudeOutputPane）工具条 SHALL 在「加载更早事件」按钮旁提供
「查看提示词」按钮，点击后拉取
`GET /api/runs/<run_id>/prompt?project=<name>` 并以 Modal 展示提示词全文：

- 展示形态：等宽字体、只读、可滚动（长提示词不得撑爆弹窗）、显示字符数、
  提供一键复制按钮。
- `prompt` 为 `null`（功能上线前的历史 run）时，Modal 内展示明确提示文案
  （如「该 run 无提示词记录（早于功能上线）」），不报错、不空白。
- 端点失败（网络/500）时 Modal 内展示错误信息，MUST NOT 静默空白。
- 按钮对所有 run 可点（是否含 prompt 由端点返回决定），MUST NOT 因 run 历史状态
  禁用。

数据层 `get_run_prompt` SHALL 复用既有 `_resolve_run_file`（含 `archive/`
回退），从文件头向尾扫描首个 `type=="prompt"` 行（命中即 early-exit），单行
json 解析容错（坏行跳过，`errors="replace"` 解码）。

#### Scenario: 查看含记录的 run

- **WHEN** 用户在运行记录窗口点击「查看提示词」，该 run 产物含 prompt 行
- **THEN** Modal 展示与落盘 `text` 逐字节一致的提示词全文、字符数与可用复制按钮

#### Scenario: 历史 run 无记录

- **WHEN** 用户查看一个早于功能上线的 run（产物无 prompt 行）
- **THEN** Modal 展示「无提示词记录」提示，不报错

#### Scenario: 已归档 run 可查看

- **WHEN** run 产物已迁入 `.fenix/runs/archive/`，用户在其历史记录窗口点击
  「查看提示词」
- **THEN** 端点经 archive 回退解析成功，Modal 正常展示

#### Scenario: 端点失败有反馈

- **WHEN** 端点返回 500 或网络失败
- **THEN** Modal 内展示错误信息，用户可关闭重试
