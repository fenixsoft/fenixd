# multi-kind-scenario-model — 场景多形态模型与词表

## ADDED Requirements

### Requirement: 场景 kind 字段与缺省兼容

`TestScenario` SHALL 新增 `kind` 字段，取值限定 `{web, cli, api}`，缺省 `web`。`from_dict` MUST 对缺失 `kind` 的存量场景文件按 `web` 处理，存量 `test_scenarios.json` 零迁移。

#### Scenario: 存量场景缺省 web
- **WHEN** 加载不含 `kind` 字段的存量场景定义（含 navigate 步骤与 DOM 断言）
- **THEN** 解析后 `kind == "web"`，场景验收与执行行为与改造前完全一致

#### Scenario: 非法 kind 拒绝
- **WHEN** 场景定义 `kind: "desktop"`
- **THEN** 场景验收报「未知 kind」错误，场景集被拒绝（不静默按 web 处理）

### Requirement: 单场景单 kind 与跨 kind 编排

单个场景内的全部步骤 MUST 属于同一 kind 的词表（不混排）。同一场景集内不同场景 MAY 混用不同 kind；`depends_on` MUST 允许跨 kind 引用；场景 id MUST 在场景集内全局唯一。跨 kind 顺序编排 MUST 通过 `depends_on` 表达，拓扑排序保证被依赖场景先完成。

#### Scenario: 混合 spec 场景集混排
- **WHEN** 场景集包含 `kind: api` 场景 A 与 `kind: web` 场景 B，且 B 声明 `depends_on: [A]`
- **THEN** 验收通过，执行时 A 先完成、B 后执行

#### Scenario: 场景内混排步骤拒绝
- **WHEN** `kind: api` 的场景内出现 `click` 步骤
- **THEN** 场景验收报「步骤不属于 api 词表」错误并打回 plan

### Requirement: CLI 词表与执行语义

CliRunner 的场景步骤 SHALL 限定为 `run`：`command`（字符串=经 shell 执行、列表=argv 直接执行，与 prepare 约定同源）、`cwd`（相对验证树根）、`env`（值支持 `{env:VAR}` 插值）、`stdin`、`timeout`、`as`（命名结果）。CLI 断言 SHALL 限定为：`exit_code`（第1层，缺省期望 0）、`file_exists`（第1层，`path` 相对验证树根、`exists` 缺省 true）、`output_match`（第3层，`stream` ∈ stdout/stderr/combined、`mode` ∈ exact/contains/regex、`negate` 可选）、`file_content`（第3层，同 mode/negate）、`json_output`（第3层，`step` 指定解析哪个命名结果的 stdout、`path`、`expected`、`mode`）、`dir_contains`（第1层，`glob`、`min`/`max` 计数）。

CLI 步骤执行语义 MUST 满足：
- **非零退出码不判步骤失败**：结果照常记录（exit_code/stdout/stderr），由 `exit_code` 断言仲裁
- **超时强杀 = 步骤失败**：超时后杀进程组（防孤儿子进程），场景按失败处理
- **信号死亡 = error**：被信号终止（如段错误）判 `error` 而非 `fail`，不进 product-bug 管道
- argv 形态命令二进制不存在（`FileNotFoundError`）判 `error`

证据纪律 MUST 满足：stdout/stderr 捕获超过 64KB 截断并带截断标记；场景结果 `screenshots` / `visual_results` 恒为空列表。

#### Scenario: 错误路径测试不误判步骤失败
- **WHEN** CLI 场景执行 `run` 命令退出码为 1，场景断言 `exit_code` 期望 1
- **THEN** 步骤记录 exit_code=1 且不判失败，断言通过，场景 status 为 pass

#### Scenario: 超时判步骤失败
- **WHEN** `run` 步骤超出声明的 `timeout` 仍未退出
- **THEN** 杀死该命令整个进程组，步骤记为失败，场景 status 为 fail

#### Scenario: 段错误判 error 不进 product-bug 管道
- **WHEN** `run` 的 argv 命令被 SIGSEGV 终止
- **THEN** 场景 status 为 `error`（非 `fail`），裁决不据此派生 product-bug

#### Scenario: 输出超限截断
- **WHEN** 某命令 stdout 超过 64KB
- **THEN** 证据只保留截断后内容并带截断标记，报告文件不因超长输出膨胀

### Requirement: API 词表与响应捕获

ApiRunner 的场景步骤 SHALL 限定为 `http_request` 与 `sse_connect`：
- `http_request`：`method`、`url`（绝对 URL，origin 由框架改写）、`headers`（值支持 `{env:VAR}` 插值）、`body` + `body_type`（json/text）、`timeout`、`as`（命名响应）
- `sse_connect`：`url`、`duration`（收集窗口秒数）、`as`

API 断言 SHALL 限定为：`status_code`（第1层，`expected` int）、`json_path`（第3层，`path`、`expected` 为 JSON 值比较、`mode`）、`response_header`（第3层，`header`、`expected`、`mode`）、`body_contains`（第3层，`expected`、`mode`）、`json_schema`（第3层，`schema`）、`latency_under`（第4层，`expected` 毫秒上限）、`sse_event_matches`（第3层）、`sse_event_count`（第1层，下限）。

断言引用响应 MUST 通过 `response` 字段指向命名捕获（缺省=最近一次响应）。每个 `http_request` 响应 MUST 捕获 `{status, headers, body, json, latency_ms}`；`sse_connect` MUST 捕获窗口内事件列表。证据中响应体超 64KB MUST 截断。

#### Scenario: 多请求流命名捕获
- **WHEN** 场景依次执行 POST（`as: "create"`）与 GET 两个请求，断言声明 `response: "create"` 断言其状态码
- **THEN** 断言作用于 create 命名的响应而非最近一次（GET）响应

#### Scenario: JSONPath 断言
- **WHEN** 响应体为 `{"data": {"id": "x1"}}`，断言 `json_path` path=`data.id` expected=`x1`
- **THEN** 断言通过；path 求值失败或值不等时断言失败并在结果中记录 actual

### Requirement: 断言分层语义跨 kind 统一

三套词表共用现有分层语义：第 1 层存在性/状态、第 3 层内容正确性为确定性断言（失败=一定是 Bug）；第 4 层为启发式阈值断言（失败=warning，需结合上下文判定）。`ASSERTION_LAYERS` MUST 允许按 kind 稀疏（CLI/API 无第 2 层）。场景状态判定规则（步骤失败=fail、1-3 层断言失败=fail、仅 4 层失败=warning）MUST 对三种 kind 一致，复用现有 `_determine_scenario_status` 逻辑。

#### Scenario: API 第4层断言失败降级 warning
- **WHEN** api 场景仅 `latency_under` 断言失败（其余全过）
- **THEN** 场景 status 为 `warning` 而非 `fail`

#### Scenario: CLI 第3层断言失败判 fail
- **WHEN** cli 场景 `output_match` 断言失败
- **THEN** 场景 status 为 `fail`，进入裁决 product-bug 归因管道

### Requirement: per-kind 场景验收校验

场景验收 MUST 委托所属 Runner 的 `validate`：各 Runner 校验本 kind 的 action/断言类型/必填字段（含 WebRunner 持有的 navigate 绝对 URL 硬要求）；未知 kind、跨词表步骤误用、必填字段缺失均报错。验收失败 MUST 不启动任何 Runner、不执行任何场景，产出带 `env_error` 的空报告并退回 plan（上限机制复用现有）。

#### Scenario: navigate 硬要求归属 WebRunner
- **WHEN** `kind: web` 场景缺少 navigate 步骤
- **THEN** 验收报「缺少 navigate 步骤」错误打回 plan；同样缺步骤的 cli/api 场景不受此要求约束

#### Scenario: 验收失败不启浏览器
- **WHEN** 场景集存在任一验收错误
- **THEN** 引擎不启动浏览器、不执行任何场景，返回带 env_error 的空报告退回 plan
