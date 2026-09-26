## ADDED Requirements

### Requirement: 后端健康检测端点

系统 SHALL 提供 `POST /api/config/llm-health-check` 端点，接收 JSON body
`{"baseurl": "<string>", "apikey": "<string>", "model": "<string>"}`，向
`{baseurl}/v1/messages`（baseurl 去尾部 `/`）发送一条 Anthropic 兼容最小消息请求
（`role: user`、`content: "hello"`、`max_tokens: 64`），并返回检测结果。请求头构造
MUST 与既有先例 `bin/probe_prompt_cache.py` 一致（`x-api-key` + `anthropic-version:
2023-06-01`，apikey 非空时附加 `Authorization: Bearer`）。端点 MUST NOT 落盘
apikey 或完整响应内容。

#### Scenario: 模型正常回复

- **WHEN** 端点收到合法参数且上游在超时窗口内返回 HTTP 200、响应含非空文本 content
- **THEN** 响应体为 `{"ok": true, "latency_ms": <正整数>, "model": "<回显请求的 model>"}`，
  其中 `latency_ms` 为从发请求到收齐响应的实测耗时

#### Scenario: 上游返回 HTTP 错误

- **WHEN** 上游返回非 200（如 401 / 404 / 429 / 5xx）
- **THEN** 响应体为 `{"ok": false, "latency_ms": <实测耗时>, "error_kind": "http_error", "status": <HTTP 状态码>, "error": "<截断后的响应片段，≤200 字符>"}`，端点自身 HTTP 状态仍为 200

#### Scenario: 连接失败或超时

- **WHEN** 连接被拒 / DNS 失败 / baseurl 非法 / 上游在 15 秒内未返回
- **THEN** 响应体为 `{"ok": false, "latency_ms": <实测耗时或 0>, "error_kind": "<connection_error|timeout>", "error": "<简要原因>"}`；超时阈值为 15 秒（模块级常量单源定义）

#### Scenario: 200 但无文本回复

- **WHEN** 上游返回 200 但解析不到非空文本 content（如空 content、响应非合法 JSON）
- **THEN** 响应体为 `{"ok": false, "latency_ms": <实测耗时>, "error_kind": "empty_reply", "error": "<简要原因>"}`

#### Scenario: 缺参拦截

- **WHEN** body 缺少 baseurl / apikey / model 任一字段或为空串
- **THEN** 端点返回 HTTP 400 与 `{"error": "<指明缺失字段>"}`，不发起上游请求

### Requirement: 模型页签文字按钮

「模型」页签每张 Provider 卡片标题栏 SHALL 在「删除」图标左侧新增文字按钮
「健康检测」。点击后使用该卡片**表单当前值**（名称 / Base URL / API Key /
默认模型名，含未保存修改）调用健康检测端点；Base URL / API Key / 默认模型名
任一为空时 MUST 直接提示补齐、不发起请求。

#### Scenario: 检测成功展示

- **WHEN** 用户点击某 Provider 卡片的「健康检测」且端点返回 `ok: true`
- **THEN** 按钮进入检测中态（加载中、防重复点击），完成后在卡片标题栏内联显示
  绿色「正常 · <X.Xs>」（秒，一位小数），并弹出成功 message

#### Scenario: 检测失败展示

- **WHEN** 端点返回 `ok: false`
- **THEN** 内联显示红色「失败 · <原因分类>」，鼠标悬停 tooltip 展示完整错误详情；
  同时弹出失败 message

#### Scenario: 未保存修改即测

- **WHEN** 用户修改了 Base URL / API Key / 默认模型名但尚未点「保存」，随后点击「健康检测」
- **THEN** 检测按修改后的表单当前值执行（无需先保存）

#### Scenario: 表单值不完整不发请求

- **WHEN** 用户点击「健康检测」时该卡片 Base URL / API Key / 默认模型名任一为空
- **THEN** 仅弹出补齐提示、不发起检测请求

### Requirement: 模型分配页签行内图标按钮

「模型分配」页签每个 Provider 行 SHALL 在「删除此行」图标**之前**新增健康检测
图标按钮（icon-only，带 title/aria-label「健康检测」）。检测目标 MUST 按运行期
同款链解析实际模型名：行内模型输入非空用行内值；否则用该角色卡片「角色级默认
模型」；仍为空则用所选 Provider 的默认模型名。Provider 的 baseurl/apikey 优先
从本表单正在编辑的 Provider 列表按行内所选 Provider 名解析，找不到时回退已保存
配置（当前作用域 config）。解析不出 baseurl / apikey / model 任一时 MUST 直接
提示原因、不发起请求。

#### Scenario: 行内模型已填

- **WHEN** 某行 Provider=A、模型=mdl-x，点击该行健康检测图标
- **THEN** 以表单中 Provider A 的 baseurl/apikey + 模型 mdl-x 发起检测，结果内联
  显示在该行（口径同「模型页签文字按钮」的成功/失败展示）

#### Scenario: 行内模型留空按链解析

- **WHEN** 某行模型留空、所在角色「角色级默认模型」为空、Provider A 默认模型名=mdl-default
- **THEN** 以模型 mdl-default 发起检测

#### Scenario: 引用了表单中不存在的 Provider

- **WHEN** 某行所选 Provider 名不在当前表单 Provider 列表中（如引用仅存在于已保存配置的 Provider）
- **THEN** 从已保存配置（当前作用域）按名解析 baseurl/apikey 后发起检测

#### Scenario: 检测中防重复

- **WHEN** 某行检测进行中用户再次点击该行健康检测图标
- **THEN** 该按钮处于禁用态，不并发发起第二次请求；其它行不受影响

#### Scenario: Provider 无法解析不发请求

- **WHEN** 某行所选 Provider 名在表单与已保存配置中均解析不到 baseurl/apikey，或模型链（行内 → 角色级默认 → Provider 默认）解析结果为空
- **THEN** 仅弹出指明原因的提示、不发起检测请求，其它行不受影响
